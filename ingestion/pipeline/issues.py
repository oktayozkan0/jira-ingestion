"""Issue ingestion (JQL search -> ``jira_issues`` + changelog + links).

Issues are pulled per team with a ``project = <key>`` JQL query, narrowed by an
``updated >=`` lower bound and ordered oldest-first so the watermark can advance
to the newest ``updated`` seen. Two modes share the path:

* **incremental** resumes from the team's ``last_entity_updated_at`` watermark
  (falling back to the configured start date on the first run);
* **backfill** ignores the watermark and works from the team's
  ``tracking_start_date`` (or the global default start date).

Per issue we also ingest the changelog (``expand=changelog``, falling back to
the paginated endpoint when truncated) into ``jira_issue_field_changes``. Parent
and epic links are applied in a second pass once every issue in the batch
exists, so forward references within a run resolve correctly. The watermark is
advanced only after the fetch loop completes without raising. Sprint membership
is handled separately.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, tzinfo
from typing import TYPE_CHECKING, Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ingestion.atlassian.jira import jql
from ingestion.config import settings
from ingestion.enums import JiraSyncEntityType, JiraSyncRunStatus, JiraSyncTrigger
from ingestion.models import JiraIssue, JiraIssueFieldChange, TrackedJiraTeam
from ingestion.pipeline.membership import ingest_sprint_membership
from ingestion.pipeline.parsing import parse_jira_date, parse_jira_datetime
from ingestion.pipeline.references import (
    resolve_issue_type,
    resolve_priority,
    resolve_status,
)
from ingestion.pipeline.upsert import upsert
from ingestion.pipeline.users import resolve_user
from ingestion.sync import SyncStateRepository, sync_run
from ingestion.sync.counters import SyncCounters

if TYPE_CHECKING:
    from ingestion.atlassian.jira import Jira

logger = logging.getLogger(__name__)

IngestMode = Literal["incremental", "backfill"]

# A (child issue id, parent issue id, epic issue key) reference collected during
# the fetch loop and resolved into FK ids afterwards.
LinkRef = tuple[str, str | None, str | None]


def resolve_account_timezone(name: str | None) -> tzinfo:
    """Timezone JQL date literals are evaluated in (the searching account's tz)."""
    if not name:
        return timezone.utc
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        logger.warning("Unknown Jira timezone %r; using UTC for JQL", name)
        return timezone.utc


def _issue_fields() -> list[str]:
    fields = [
        "summary",
        "issuetype",
        "status",
        "priority",
        "assignee",
        "reporter",
        "creator",
        "resolution",
        "resolutiondate",
        "duedate",
        "created",
        "updated",
        "parent",
        settings.jira_story_points_field,
        settings.jira_sprint_field,
    ]
    if settings.jira_epic_link_field:
        fields.append(settings.jira_epic_link_field)
    return fields


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _id_of(obj: Any) -> int | None:
    return obj.id if obj is not None else None


def _start_datetime(team: TrackedJiraTeam) -> datetime | None:
    start = team.tracking_start_date or settings.default_backfill_start_date
    if start is None:
        return None
    return datetime(start.year, start.month, start.day, tzinfo=timezone.utc)


def _resolve_since(
    team: TrackedJiraTeam, mode: IngestMode, watermark: datetime | None
) -> datetime | None:
    if mode == "backfill":
        return _start_datetime(team)
    # incremental: resume from the watermark, or seed from the start date.
    return watermark if watermark is not None else _start_datetime(team)


def _build_issue_jql(project_key: str, since: datetime | None, tz: tzinfo) -> str:
    clauses = [f"project = {jql.quote(project_key)}"]
    if since is not None:
        literal = since.astimezone(tz).strftime("%Y-%m-%d %H:%M")
        clauses.append(f'updated >= "{literal}"')
    return " AND ".join(clauses) + " ORDER BY updated ASC"


def _parent_ref(issue: dict[str, Any]) -> str | None:
    parent = (issue.get("fields") or {}).get("parent") or {}
    pid = parent.get("id")
    return str(pid) if pid is not None else None


def _epic_ref(issue: dict[str, Any]) -> str | None:
    field = settings.jira_epic_link_field
    if not field:
        return None
    value = (issue.get("fields") or {}).get(field)
    if isinstance(value, str):
        return value or None
    if isinstance(value, dict):
        return value.get("key")
    return None


async def _upsert_issue(
    team: TrackedJiraTeam, issue: dict[str, Any], counters: SyncCounters
) -> JiraIssue:
    """Upsert one issue's core row and return it (so callers have its id)."""
    fields = issue.get("fields") or {}
    resolution = fields.get("resolution") or {}

    values = {
        "team_id": team.id,
        "issue_key": issue.get("key") or "",
        "issue_type_id": await resolve_issue_type(fields.get("issuetype")),
        "status_id": await resolve_status(fields.get("status")),
        "priority_id": await resolve_priority(fields.get("priority")),
        "summary": (fields.get("summary") or "")[:500],
        "story_points": _to_float(fields.get(settings.jira_story_points_field)),
        "assignee_id": _id_of(await resolve_user(fields.get("assignee"))),
        "reporter_id": _id_of(await resolve_user(fields.get("reporter"))),
        "creator_id": _id_of(await resolve_user(fields.get("creator"))),
        "resolution_name": resolution.get("name") if resolution else None,
        "resolved_at": parse_jira_datetime(fields.get("resolutiondate")),
        "due_date": parse_jira_date(fields.get("duedate")),
        "jira_created_at": parse_jira_datetime(fields.get("created")),
        "jira_updated_at": parse_jira_datetime(fields.get("updated")),
    }
    row, _ = await upsert(
        JiraIssue,
        natural_key={"jira_issue_id": str(issue["id"])},
        values=values,
        counters=counters,
    )
    return row


async def _load_histories(
    jira: "Jira", issue: dict[str, Any]
) -> list[dict[str, Any]]:
    """An issue's changelog histories, fetching the full set when truncated.

    Loaded once and shared by changelog and sprint-membership ingestion.
    """
    changelog = issue.get("changelog") or {}
    histories = changelog.get("histories") or []
    total = changelog.get("total")
    if total is not None and total > len(histories):
        histories = [h async for h in jira.issues.iter_changelog(str(issue["id"]))]
    return histories


async def _ingest_changelog(
    issue_row_id: int,
    run_id: int | None,
    counters: SyncCounters,
    histories: list[dict[str, Any]],
) -> None:
    """Upsert an issue's changelog field changes.

    The unique key is (issue, changelog id, field), but a single history can
    carry several items for the same field — e.g. multiple attachments or
    labels changed in one action. Only one row can be stored per field per
    history, so same-field items are collapsed (last item wins) before
    upserting, which keeps a multi-item history from colliding with itself.
    """
    for history in histories:
        changed_at = parse_jira_datetime(history.get("created"))
        author = await resolve_user(history.get("author"))
        changelog_id = (
            str(history["id"]) if history.get("id") is not None else None
        )
        items_by_field: dict[str, dict[str, Any]] = {}
        for item in history.get("items") or []:
            items_by_field[item.get("field") or ""] = item
        for field_name, item in items_by_field.items():
            await upsert(
                JiraIssueFieldChange,
                natural_key={
                    "issue_id": issue_row_id,
                    "jira_changelog_id": changelog_id,
                    "field_name": field_name,
                },
                values={
                    "field_id": item.get("fieldId"),
                    "field_type": item.get("fieldtype"),
                    "from_value": item.get("fromString"),
                    "from_value_id": item.get("from"),
                    "to_value": item.get("toString"),
                    "to_value_id": item.get("to"),
                    "changed_at": changed_at,
                    "changed_by_id": _id_of(author),
                },
                create_only={"source_sync_run_id": run_id},
                counters=counters,
            )


async def _apply_links(links: list[LinkRef]) -> None:
    """Resolve collected parent/epic references to FK ids after the batch lands.

    Runs once every issue in the batch exists, so same-run forward references
    resolve. Unresolvable references (target not yet ingested) are left for a
    later run. Only genuine changes are written.
    """
    for child_jid, parent_jid, epic_key in links:
        if parent_jid is None and epic_key is None:
            continue
        child = await JiraIssue.get_or_none(jira_issue_id=child_jid)
        if child is None:
            continue

        updates: dict[str, Any] = {}
        if parent_jid is not None:
            parent = await JiraIssue.get_or_none(jira_issue_id=parent_jid)
            if parent is not None and child.parent_issue_id != parent.id:
                updates["parent_issue_id"] = parent.id
        if epic_key is not None:
            epic = await JiraIssue.get_or_none(issue_key=epic_key)
            if epic is not None and child.epic_issue_id != epic.id:
                updates["epic_issue_id"] = epic.id
        if updates:
            await JiraIssue.filter(id=child.id).update(**updates)


async def ingest_issues_for_team(
    jira: "Jira",
    team: TrackedJiraTeam,
    *,
    mode: IngestMode = "incremental",
    jira_timezone: tzinfo = timezone.utc,
    triggered_by: JiraSyncTrigger = JiraSyncTrigger.SCHEDULED,
) -> None:
    state_repo = SyncStateRepository()
    watermark = await state_repo.get_watermark(team.id, JiraSyncEntityType.ISSUES)
    since = _resolve_since(team, mode, watermark)
    query = _build_issue_jql(team.key, since, jira_timezone)
    run_trigger = (
        JiraSyncTrigger.BACKFILL if mode == "backfill" else triggered_by
    )

    async with sync_run(
        JiraSyncEntityType.ISSUES,
        team_id=team.id,
        team_label=team.key,
        triggered_by=run_trigger,
    ) as ctx:
        logger.info("issue sync | team=%s mode=%s jql=%s", team.key, mode, query)
        max_updated: datetime | None = None
        links: list[LinkRef] = []
        async for issue in jira.issues.iter_search(
            query,
            page_size=settings.jira_page_size,
            fields=_issue_fields(),
            expand="changelog",
        ):
            ctx.counters.add(fetched=1)
            row = await _upsert_issue(team, issue, ctx.counters)
            histories = await _load_histories(jira, issue)
            await _ingest_changelog(row.id, ctx.run.id, ctx.counters, histories)
            await ingest_sprint_membership(issue, row, histories, ctx.counters)
            links.append((str(issue["id"]), _parent_ref(issue), _epic_ref(issue)))
            updated = row.jira_updated_at
            if updated is not None and (max_updated is None or updated > max_updated):
                max_updated = updated

        await _apply_links(links)

        # Advance the watermark only after a clean pass over every page.
        status = (
            JiraSyncRunStatus.PARTIAL
            if ctx.counters.failed
            else JiraSyncRunStatus.SUCCESS
        )
        state_fields: dict[str, Any] = {
            "last_synced_at": datetime.now(timezone.utc),
            "last_run_id": ctx.run.id,
            "last_run_status": status,
            "error_message": None,
        }
        if max_updated is not None:
            state_fields["last_entity_updated_at"] = max_updated
        await state_repo.upsert(
            team.id, JiraSyncEntityType.ISSUES, **state_fields
        )
