"""Watermark store for incremental Jira syncs (``jira_sync_state``).

One row per ``(team_id, entity_type)`` holds where the last successful sync got
to. ``last_entity_updated_at`` is the high-water mark the incremental fetch
resumes from; backfill ignores it and works from the team's configured start
date instead.
"""

from datetime import datetime
from typing import Any

from ingestion.enums import JiraSyncEntityType, JiraSyncRunStatus
from ingestion.models import JiraSyncState

_UNSET: Any = object()


class SyncStateRepository:
    async def get(
        self, team_id: int, entity_type: JiraSyncEntityType
    ) -> JiraSyncState | None:
        return await JiraSyncState.get_or_none(
            team_id=team_id, entity_type=entity_type
        )

    async def get_watermark(
        self, team_id: int, entity_type: JiraSyncEntityType
    ) -> datetime | None:
        """The point an incremental sync should resume from, or None to backfill."""
        state = await self.get(team_id, entity_type)
        return state.last_entity_updated_at if state else None

    async def upsert(
        self,
        team_id: int,
        entity_type: JiraSyncEntityType,
        *,
        last_synced_at: datetime | None = _UNSET,
        last_entity_updated_at: datetime | None = _UNSET,
        last_cursor: str | None = _UNSET,
        last_run_status: JiraSyncRunStatus | None = _UNSET,
        last_run_id: int | None = _UNSET,
        error_message: str | None = _UNSET,
    ) -> JiraSyncState:
        """Create or merge the watermark row.

        Only arguments that are explicitly passed are written; omitted fields are
        left untouched, so advancing ``last_synced_at`` never accidentally clears
        an existing ``last_entity_updated_at`` watermark.
        """
        candidate: dict[str, Any] = {
            "last_synced_at": last_synced_at,
            "last_entity_updated_at": last_entity_updated_at,
            "last_cursor": last_cursor,
            "last_run_status": last_run_status,
            "last_run_id": last_run_id,
            "error_message": error_message,
        }
        provided = {k: v for k, v in candidate.items() if v is not _UNSET}

        state = await self.get(team_id, entity_type)
        if state is None:
            return await JiraSyncState.create(
                team_id=team_id, entity_type=entity_type, **provided
            )
        for field, value in provided.items():
            setattr(state, field, value)
        await state.save()
        return state
