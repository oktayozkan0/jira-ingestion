"""Audit trail for ingestion runs (``jira_sync_runs``).

Every fetch loop runs inside :func:`sync_run`, which opens a ``RUNNING`` audit
row, and on exit stamps it ``SUCCESS`` / ``PARTIAL`` / ``FAILED`` with the
volume counters and emits a single structured log line carrying the run's
status, team, entity, duration, and data volume.
"""

import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone

from ingestion.enums import JiraSyncEntityType, JiraSyncRunStatus, JiraSyncTrigger
from ingestion.models import JiraSyncRun
from ingestion.sync.counters import SyncCounters

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SyncRunRepository:
    async def start(
        self,
        entity_type: JiraSyncEntityType,
        *,
        team_id: int | None = None,
        triggered_by: JiraSyncTrigger = JiraSyncTrigger.SCHEDULED,
        started_at: datetime | None = None,
    ) -> JiraSyncRun:
        return await JiraSyncRun.create(
            team_id=team_id,
            entity_type=entity_type,
            status=JiraSyncRunStatus.RUNNING,
            triggered_by=triggered_by,
            started_at=started_at or _utcnow(),
        )

    async def finish(
        self,
        run: JiraSyncRun,
        *,
        status: JiraSyncRunStatus,
        counters: SyncCounters,
        finished_at: datetime | None = None,
        error_message: str | None = None,
    ) -> JiraSyncRun:
        run.status = status
        run.finished_at = finished_at or _utcnow()
        run.records_fetched = counters.fetched
        run.records_created = counters.created
        run.records_updated = counters.updated
        run.records_deleted = counters.deleted
        run.records_failed = counters.failed
        run.error_message = error_message  # type: ignore[assignment]
        await run.save()
        return run


@dataclass
class RunContext:
    """Handle yielded by :func:`sync_run`; mutate ``counters`` as work proceeds."""

    run: JiraSyncRun
    counters: SyncCounters
    entity_type: JiraSyncEntityType
    team_id: int | None
    started_at: datetime


@asynccontextmanager
async def sync_run(
    entity_type: JiraSyncEntityType,
    *,
    team_id: int | None = None,
    team_label: str | None = None,
    triggered_by: JiraSyncTrigger = JiraSyncTrigger.SCHEDULED,
    repository: SyncRunRepository | None = None,
):
    """Wrap a fetch loop in a ``jira_sync_runs`` audit row with run logging.

    On a clean exit the run is marked ``SUCCESS`` (or ``PARTIAL`` if any records
    failed). On exception it is marked ``FAILED`` with the error captured, then
    the exception is re-raised so the caller decides how to proceed.
    """
    repo = repository or SyncRunRepository()
    label = team_label or (str(team_id) if team_id is not None else "-")
    started_at = _utcnow()
    run = await repo.start(
        entity_type, team_id=team_id, triggered_by=triggered_by, started_at=started_at
    )
    counters = SyncCounters()
    ctx = RunContext(
        run=run,
        counters=counters,
        entity_type=entity_type,
        team_id=team_id,
        started_at=started_at,
    )
    logger.info(
        "sync start | entity=%s team=%s run_id=%s trigger=%s",
        entity_type.value,
        label,
        run.id,
        triggered_by.value,
    )
    try:
        yield ctx
    except Exception as exc:
        finished_at = _utcnow()
        duration = (finished_at - started_at).total_seconds()
        await repo.finish(
            run,
            status=JiraSyncRunStatus.FAILED,
            counters=counters,
            finished_at=finished_at,
            error_message=f"{type(exc).__name__}: {exc}",
        )
        logger.exception(
            "sync FAILED | entity=%s team=%s run_id=%s duration=%.2fs %s",
            entity_type.value,
            label,
            run.id,
            duration,
            counters.summary(),
        )
        raise
    else:
        finished_at = _utcnow()
        duration = (finished_at - started_at).total_seconds()
        status = (
            JiraSyncRunStatus.PARTIAL
            if counters.failed
            else JiraSyncRunStatus.SUCCESS
        )
        await repo.finish(
            run, status=status, counters=counters, finished_at=finished_at
        )
        logger.info(
            "sync %s | entity=%s team=%s run_id=%s duration=%.2fs %s",
            status.value,
            entity_type.value,
            label,
            run.id,
            duration,
            counters.summary(),
        )
