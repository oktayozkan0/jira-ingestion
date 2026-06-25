"""Issue ingestion (JQL search -> ``jira_issues``).

Issues are pulled per team with a ``project = <key>`` JQL query, narrowed by an
``updated >=`` lower bound and ordered oldest-first so the watermark can advance
to the newest ``updated`` seen. Two modes share the path:

* **incremental** resumes from the team's ``last_entity_updated_at`` watermark
  (falling back to the configured start date on the first run);
* **backfill** ignores the watermark and works from the team's
  ``tracking_start_date`` (or the global default start date).

Embedded issue-type / status / priority objects and assignee / reporter /
creator users are resolved on the fly. The watermark is advanced only after the
fetch loop completes without raising, so a failure mid-run is retried from the
same point. Parent/epic links, changelog and sprint membership are handled
separately.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, tzinfo
from typing import TYPE_CHECKING, Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ingestion.atlassian.jira import jql
from ingestion.config import settings
from ingestion.enums import JiraSyncEntityType, JiraSyncRunStatus, JiraSyncTrigger
from ingestion.models import JiraIssue, TrackedJiraTeam
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
    return [
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
        settings.jira_story_points_field,
    ]


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


async def _upsert_issue(
    team: TrackedJiraTeam, issue: dict[str, Any], counters: SyncCounters
) -> datetime | None:
    """Upsert one issue's core row; return its ``updated`` time for the watermark."""
    fields = issue.get("fields") or {}
    resolution = fields.get("resolution") or {}
    updated = parse_jira_datetime(fields.get("updated"))

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
        "jira_updated_at": updated,
    }
    await upsert(
        JiraIssue,
        natural_key={"jira_issue_id": str(issue["id"])},
        values=values,
        counters=counters,
    )
    return updated


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
        async for issue in jira.issues.iter_search(
            query, page_size=settings.jira_page_size, fields=_issue_fields()
        ):
            ctx.counters.add(fetched=1)
            updated = await _upsert_issue(team, issue, ctx.counters)
            if updated is not None and (max_updated is None or updated > max_updated):
                max_updated = updated

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
