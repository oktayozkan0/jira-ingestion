"""Sprint ingestion (Agile API -> ``jira_sprints``).

Sprints are listed per board, but only Scrum boards have them, so other board
types are skipped (their sprint endpoint returns 400). ``team_id`` is
denormalised from the board so sprints can be filtered by team without a join.
All of a team's sprints are ingested under one ``SPRINTS`` run.
"""

from __future__ import annotations

import logging
from functools import partial
from typing import TYPE_CHECKING, Any

from ingestion.enums import (
    JiraBoardType,
    JiraSprintState,
    JiraSyncEntityType,
    JiraSyncTrigger,
)
from ingestion.models import JiraBoard, JiraSprint, TrackedJiraTeam
from ingestion.pipeline.dedupe import once
from ingestion.pipeline.parsing import parse_jira_datetime
from ingestion.pipeline.upsert import upsert
from ingestion.sync import sync_run
from ingestion.sync.counters import SyncCounters

if TYPE_CHECKING:
    from ingestion.atlassian.jira import Jira

logger = logging.getLogger(__name__)


def _sprint_state(value: str | None) -> JiraSprintState:
    try:
        return JiraSprintState((value or "").upper())
    except ValueError:
        logger.warning("Unknown sprint state %r; defaulting to FUTURE", value)
        return JiraSprintState.FUTURE


async def _upsert_sprint(
    board: JiraBoard,
    team: TrackedJiraTeam,
    payload: dict[str, Any],
    counters: SyncCounters,
) -> JiraSprint | None:
    sprint, _ = await upsert(
        JiraSprint,
        natural_key={"jira_sprint_id": int(payload["id"])},
        values={
            "board_id": board.id,
            "team_id": team.id,
            "name": payload.get("name") or "",
            "state": _sprint_state(payload.get("state")),
            "goal": payload.get("goal"),
            "start_date": parse_jira_datetime(payload.get("startDate")),
            "end_date": parse_jira_datetime(payload.get("endDate")),
            "complete_date": parse_jira_datetime(payload.get("completeDate")),
        },
        counters=counters,
    )
    return sprint


async def ingest_sprints_for_team(
    jira: "Jira",
    team: TrackedJiraTeam,
    *,
    boards: list[JiraBoard] | None = None,
    triggered_by: JiraSyncTrigger = JiraSyncTrigger.SCHEDULED,
) -> list[JiraSprint]:
    """Upsert sprints for each of the team's Scrum boards.

    ``boards`` lets the caller pass the rows returned by board ingestion; when
    omitted, the team's non-deleted boards are loaded from the database.
    """
    if boards is None:
        boards = await JiraBoard.filter(team_id=team.id, is_deleted=False)

    sprints: list[JiraSprint] = []
    async with sync_run(
        JiraSyncEntityType.SPRINTS,
        team_id=team.id,
        team_label=team.key,
        triggered_by=triggered_by,
    ) as ctx:
        for board in boards:
            if board.board_type != JiraBoardType.SCRUM:
                continue
            async for payload in jira.sprints.iter_for_board(board.jira_board_id):
                ctx.counters.add(fetched=1)
                sprint = await once(
                    "sprints",
                    int(payload["id"]),
                    partial(_upsert_sprint, board, team, payload, ctx.counters),
                )
                if sprint is not None:
                    sprints.append(sprint)
    return sprints
