"""Whole-run orchestration across all active configured teams.

One run fetches the searching account's timezone once, ingests the global
dimensions, then for each active team ingests boards -> sprints -> issues in
dependency order. Each entity runs independently and its failure is caught and
recorded, so one team (or one entity) failing does not abort the rest — the run
finishes and reports which scopes failed. Per-entity audit rows and logging are
handled by the ingesters themselves; this layer adds the run-level summary.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import TYPE_CHECKING, TypeVar

from tortoise.expressions import Q

from ingestion.enums import JiraSyncTrigger
from ingestion.models import TrackedJiraTeam
from ingestion.pipeline import (
    IngestMode,
    ingest_boards_for_team,
    ingest_issue_types,
    ingest_issues_for_team,
    ingest_priorities,
    ingest_sprints_for_team,
    ingest_statuses,
    resolve_account_timezone,
)
from ingestion.pipeline.dedupe import reset_dedupe

if TYPE_CHECKING:
    from ingestion.atlassian.jira import Jira

logger = logging.getLogger(__name__)

T = TypeVar("T")

_GLOBAL = "(global)"


@dataclass
class RunSummary:
    mode: str
    started_at: datetime
    finished_at: datetime | None = None
    teams_total: int = 0
    # (scope, entity) pairs that failed, e.g. ("RPD", "issues").
    failures: list[tuple[str, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures

    @property
    def duration_seconds(self) -> float:
        end = self.finished_at or datetime.now(timezone.utc)
        return (end - self.started_at).total_seconds()


async def list_active_teams(as_of: date | None = None) -> list[TrackedJiraTeam]:
    """Active teams eligible for ingestion as of ``as_of`` (default today).

    A team participates once it is active and its tracking has started (no start
    date, or a start date on/before the reference day), so newly added teams do
    not pull data for periods that predate them.
    """
    reference = as_of or date.today()
    return await TrackedJiraTeam.filter(
        Q(is_active=True),
        Q(tracking_start_date__isnull=True) | Q(tracking_start_date__lte=reference),
    ).order_by("key")


async def _safe(
    summary: RunSummary, scope: str, entity: str, coro: Awaitable[T]
) -> T | None:
    """Await ``coro``, recording and swallowing any failure so the run continues."""
    try:
        return await coro
    except Exception:
        logger.exception("ingestion failed | scope=%s entity=%s", scope, entity)
        summary.failures.append((scope, entity))
        return None


async def run_ingestion(
    jira: "Jira",
    *,
    mode: IngestMode = "incremental",
    team_keys: list[str] | None = None,
    triggered_by: JiraSyncTrigger = JiraSyncTrigger.SCHEDULED,
) -> RunSummary:
    summary = RunSummary(mode=mode, started_at=datetime.now(timezone.utc))
    reset_dedupe()  # fresh per-run resolution cache

    me = await jira.get_myself()
    tz = resolve_account_timezone(me.get("timeZone"))

    # Global, team-agnostic reference data first.
    await _safe(summary, _GLOBAL, "issue_types", ingest_issue_types(jira, triggered_by=triggered_by))
    await _safe(summary, _GLOBAL, "statuses", ingest_statuses(jira, triggered_by=triggered_by))
    await _safe(summary, _GLOBAL, "priorities", ingest_priorities(jira, triggered_by=triggered_by))

    teams = await list_active_teams()
    if team_keys is not None:
        wanted = set(team_keys)
        teams = [t for t in teams if t.key in wanted]
    summary.teams_total = len(teams)
    logger.info(
        "ingestion run start | mode=%s teams=%d", mode, summary.teams_total
    )

    for team in teams:
        boards = await _safe(
            summary, team.key, "boards",
            ingest_boards_for_team(jira, team, triggered_by=triggered_by),
        )
        await _safe(
            summary, team.key, "sprints",
            ingest_sprints_for_team(jira, team, boards=boards, triggered_by=triggered_by),
        )
        await _safe(
            summary, team.key, "issues",
            ingest_issues_for_team(
                jira, team, mode=mode, jira_timezone=tz, triggered_by=triggered_by
            ),
        )

    summary.finished_at = datetime.now(timezone.utc)
    _log_summary(summary)
    return summary


def _log_summary(summary: RunSummary) -> None:
    if summary.ok:
        logger.info(
            "ingestion run OK | mode=%s teams=%d duration=%.1fs",
            summary.mode, summary.teams_total, summary.duration_seconds,
        )
    else:
        failed = ", ".join(f"{scope}/{entity}" for scope, entity in summary.failures)
        logger.warning(
            "ingestion run WITH FAILURES | mode=%s teams=%d failures=%d "
            "duration=%.1fs | failed=%s",
            summary.mode, summary.teams_total, len(summary.failures),
            summary.duration_seconds, failed,
        )
