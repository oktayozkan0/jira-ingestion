"""Board ingestion (Agile API -> ``jira_boards``).

A board is the entry point to a team's sprints. Boards are resolved per team:
by the team's configured ``jira_board_id`` when set, otherwise discovered from
the team's Jira project key (a team may expose more than one board, so the table
is 1:N with teams). Each team's boards are ingested under one ``BOARDS`` run.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, AsyncIterator

from ingestion.enums import JiraBoardType, JiraSyncEntityType, JiraSyncTrigger
from ingestion.models import JiraBoard, TrackedJiraTeam
from ingestion.pipeline.upsert import upsert
from ingestion.sync import sync_run

if TYPE_CHECKING:
    from ingestion.atlassian.jira import Jira

logger = logging.getLogger(__name__)


def _board_type(value: str | None) -> JiraBoardType:
    try:
        return JiraBoardType((value or "").upper())
    except ValueError:
        logger.warning("Unknown board type %r; defaulting to SIMPLE", value)
        return JiraBoardType.SIMPLE


async def _iter_team_boards(
    jira: "Jira", team: TrackedJiraTeam
) -> AsyncIterator[dict[str, Any]]:
    if team.jira_board_id is not None:
        board = await jira.boards.get(team.jira_board_id)
        if board:
            yield board
        return
    async for board in jira.boards.iter_all(project_key_or_id=team.key):
        yield board


async def ingest_boards_for_team(
    jira: "Jira",
    team: TrackedJiraTeam,
    *,
    triggered_by: JiraSyncTrigger = JiraSyncTrigger.SCHEDULED,
) -> list[JiraBoard]:
    """Upsert all of a team's boards; return the resolved rows for sprint sync."""
    boards: list[JiraBoard] = []
    async with sync_run(
        JiraSyncEntityType.BOARDS,
        team_id=team.id,
        team_label=team.key,
        triggered_by=triggered_by,
    ) as ctx:
        async for payload in _iter_team_boards(jira, team):
            ctx.counters.add(fetched=1)
            board, _ = await upsert(
                JiraBoard,
                natural_key={"jira_board_id": int(payload["id"])},
                values={
                    "team_id": team.id,
                    "name": payload.get("name") or "",
                    "board_type": _board_type(payload.get("type")),
                },
                counters=ctx.counters,
            )
            boards.append(board)
    return boards
