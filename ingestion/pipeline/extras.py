"""Ingest the issue sub-entities that are embedded in the issue payload.

Attachments, labels and components come inline in an issue's ``fields``, so they
are ingested as each issue is processed. Issue links are also inline, but each
endpoint must be resolved to an internal issue id, so they are collected during
the issue loop and applied in a second pass once every issue in the batch exists
(mirroring parent/epic linking). Links to issues outside the tracked set are
skipped until both ends are ingested.

Labels and components (and the link rows) are immutable joins, so they use
``insert_or_ignore``; the dimension rows behind them (``jira_labels`` /
``jira_components``) are resolved once per run via :func:`once`.
"""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Any

from ingestion.models import (
    JiraAttachment,
    JiraComment,
    JiraComponent,
    JiraIssue,
    JiraIssueComponent,
    JiraIssueLabel,
    JiraIssueLink,
    JiraLabel,
    JiraWorklog,
    TrackedJiraTeam,
)
from ingestion.pipeline.dedupe import once
from ingestion.pipeline.parsing import adf_to_text, parse_jira_datetime
from ingestion.pipeline.upsert import insert_or_ignore, upsert
from ingestion.pipeline.users import resolve_user
from ingestion.sync.counters import SyncCounters

if TYPE_CHECKING:
    from ingestion.atlassian.jira import Jira

# (jira_link_id, source issue jira id, target issue jira id, link type name)
IssueLinkRef = tuple[str, str, str, str]


def _id_of(obj: Any) -> int | None:
    return obj.id if obj is not None else None


# --- dimension resolution (once per run) -----------------------------------


async def _upsert_label(name: str, counters: SyncCounters | None) -> int | None:
    obj, _ = await upsert(
        JiraLabel, natural_key={"name": name}, values={}, counters=counters
    )
    return obj.id if obj is not None else None


async def resolve_label(name: str, *, counters: SyncCounters | None = None) -> int | None:
    label = name[:128]
    if not label:
        return None
    return await once("labels", label, partial(_upsert_label, label, counters))


async def _upsert_component(
    team: TrackedJiraTeam, payload: dict[str, Any], counters: SyncCounters | None
) -> int | None:
    obj, _ = await upsert(
        JiraComponent,
        natural_key={"jira_component_id": str(payload["id"])},
        values={
            "team_id": team.id,
            "name": (payload.get("name") or "")[:255],
            "description": payload.get("description"),
            "raw_payload": payload,
        },
        counters=counters,
    )
    return obj.id if obj is not None else None


async def resolve_component(
    team: TrackedJiraTeam,
    payload: dict[str, Any] | None,
    *,
    counters: SyncCounters | None = None,
) -> int | None:
    if not payload or payload.get("id") is None:
        return None
    return await once(
        "components",
        str(payload["id"]),
        partial(_upsert_component, team, payload, counters),
    )


# --- embedded ingestion ----------------------------------------------------


async def ingest_attachments(
    issue: dict[str, Any], issue_row_id: int, counters: SyncCounters
) -> None:
    for att in (issue.get("fields") or {}).get("attachment") or []:
        created = parse_jira_datetime(att.get("created"))
        if att.get("id") is None or created is None:
            continue
        author = await resolve_user(att.get("author"))
        await upsert(
            JiraAttachment,
            natural_key={"jira_attachment_id": str(att["id"])},
            values={
                "issue_id": issue_row_id,
                "author_id": _id_of(author),
                "filename": (att.get("filename") or "")[:500],
                "size_bytes": att.get("size"),
                "mime_type": att.get("mimeType"),
                "jira_created_at": created,
            },
            counters=counters,
        )


async def ingest_labels(
    issue: dict[str, Any], issue_row_id: int, counters: SyncCounters
) -> None:
    for raw in (issue.get("fields") or {}).get("labels") or []:
        label_id = await resolve_label(str(raw))
        if label_id is None:
            continue
        await insert_or_ignore(
            JiraIssueLabel,
            natural_key={"issue_id": issue_row_id, "label_id": label_id},
            values={},
            counters=counters,
        )


async def ingest_components(
    team: TrackedJiraTeam,
    issue: dict[str, Any],
    issue_row_id: int,
    counters: SyncCounters,
) -> None:
    for comp in (issue.get("fields") or {}).get("components") or []:
        component_id = await resolve_component(team, comp)
        if component_id is None:
            continue
        await insert_or_ignore(
            JiraIssueComponent,
            natural_key={"issue_id": issue_row_id, "component_id": component_id},
            values={},
            counters=counters,
        )


# --- comments (per-issue, with pagination fallback) ------------------------


async def _load_comments(
    jira: "Jira", issue: dict[str, Any]
) -> list[dict[str, Any]]:
    comment_field = (issue.get("fields") or {}).get("comment") or {}
    comments = comment_field.get("comments") or []
    total = comment_field.get("total")
    if total is not None and total > len(comments):
        comments = [c async for c in jira.issues.iter_comments(str(issue["id"]))]
    return comments


async def ingest_comments(
    jira: "Jira",
    issue: dict[str, Any],
    issue_row_id: int,
    counters: SyncCounters,
) -> None:
    for comment in await _load_comments(jira, issue):
        created = parse_jira_datetime(comment.get("created"))
        if comment.get("id") is None or created is None:
            continue
        author = await resolve_user(comment.get("author"))
        await upsert(
            JiraComment,
            natural_key={"jira_comment_id": str(comment["id"])},
            values={
                "issue_id": issue_row_id,
                "author_id": _id_of(author),
                "body": adf_to_text(comment.get("body")),
                "jira_created_at": created,
                "jira_updated_at": parse_jira_datetime(comment.get("updated")) or created,
            },
            counters=counters,
        )


# --- worklogs (per-issue, with pagination fallback) ------------------------


async def _load_worklogs(
    jira: "Jira", issue: dict[str, Any]
) -> list[dict[str, Any]]:
    worklog_field = (issue.get("fields") or {}).get("worklog") or {}
    worklogs = worklog_field.get("worklogs") or []
    total = worklog_field.get("total")
    if total is not None and total > len(worklogs):
        worklogs = [w async for w in jira.worklogs.iter_for_issue(str(issue["id"]))]
    return worklogs


async def ingest_worklogs(
    jira: "Jira",
    issue: dict[str, Any],
    issue_row_id: int,
    counters: SyncCounters,
) -> None:
    for wl in await _load_worklogs(jira, issue):
        started = parse_jira_datetime(wl.get("started"))
        created = parse_jira_datetime(wl.get("created"))
        time_spent = wl.get("timeSpentSeconds")
        if wl.get("id") is None or started is None or created is None or time_spent is None:
            continue
        author = await resolve_user(wl.get("author"))
        await upsert(
            JiraWorklog,
            natural_key={"jira_worklog_id": str(wl["id"])},
            values={
                "issue_id": issue_row_id,
                "author_id": _id_of(author),
                "time_spent_seconds": int(time_spent),
                "comment": adf_to_text(wl.get("comment")),
                "started_at": started,
                "jira_created_at": created,
                "jira_updated_at": parse_jira_datetime(wl.get("updated")) or created,
                "raw_payload": wl,
            },
            counters=counters,
        )


# --- issue links (collect during loop, apply in a second pass) -------------


def collect_issue_links(issue: dict[str, Any], link_rows: list[IssueLinkRef]) -> None:
    """Append this issue's links as (link id, source jira id, target jira id, type).

    Normalised so the source is always the outward end of the relationship,
    making the row identical regardless of which endpoint it is seen from.
    """
    current_jid = str(issue["id"])
    for link in (issue.get("fields") or {}).get("issuelinks") or []:
        if link.get("id") is None:
            continue
        type_name = ((link.get("type") or {}).get("name") or "")[:128]
        outward = link.get("outwardIssue") or {}
        inward = link.get("inwardIssue") or {}
        if outward.get("id") is not None:
            source_jid, target_jid = current_jid, str(outward["id"])
        elif inward.get("id") is not None:
            source_jid, target_jid = str(inward["id"]), current_jid
        else:
            continue
        link_rows.append((str(link["id"]), source_jid, target_jid, type_name))


async def apply_issue_links(
    link_rows: list[IssueLinkRef], counters: SyncCounters
) -> None:
    for jira_link_id, source_jid, target_jid, type_name in link_rows:
        source = await JiraIssue.get_or_none(jira_issue_id=source_jid)
        target = await JiraIssue.get_or_none(jira_issue_id=target_jid)
        if source is None or target is None:
            continue  # an endpoint is not ingested yet; skip this run
        await insert_or_ignore(
            JiraIssueLink,
            natural_key={"jira_link_id": jira_link_id},
            values={
                "source_issue_id": source.id,
                "target_issue_id": target.id,
                "link_type_name": type_name,
                "link_direction": "outward",
            },
            counters=counters,
        )
