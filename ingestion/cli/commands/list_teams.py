"""``list-teams`` — show the tracked Jira teams in the database.

A read-only diagnostic for confirming what a run will ingest: by default it
lists active teams (the orchestrator's candidates); ``--all`` includes inactive
ones. It writes the table to stdout, so logging on stderr does not interleave.
"""

import asyncio
from datetime import date

import click

from ingestion.db import lifespan
from ingestion.logging_setup import configure_logging, get_logger
from ingestion.models import TrackedJiraTeam

logger = get_logger(__name__)


async def _fetch(include_inactive: bool) -> list[TrackedJiraTeam]:
    async with lifespan():
        query = TrackedJiraTeam.all() if include_inactive else TrackedJiraTeam.filter(
            is_active=True
        )
        return await query.order_by("key")


def _eligible(team: TrackedJiraTeam, today: date) -> bool:
    """Whether a run today would ingest this team (matches list_active_teams)."""
    if not team.is_active:
        return False
    return team.tracking_start_date is None or team.tracking_start_date <= today


@click.command(name="list-teams")
@click.option(
    "--all",
    "include_inactive",
    is_flag=True,
    default=False,
    help="Include inactive teams as well as active ones.",
)
def list_teams(include_inactive: bool) -> None:
    """List tracked Jira teams (active only by default)."""
    configure_logging()
    try:
        teams = asyncio.run(_fetch(include_inactive))
    except Exception:
        logger.exception("Failed to list teams")
        raise SystemExit(1)

    if not teams:
        click.echo("No teams found.")
        return

    today = date.today()
    header = f"{'KEY':<14} {'ACTIVE':<7} {'ELIGIBLE':<9} {'BOARD':<8} {'START':<12} NAME"
    click.echo(header)
    click.echo("-" * len(header))
    for team in teams:
        board = str(team.jira_board_id) if team.jira_board_id is not None else "-"
        start = team.tracking_start_date.isoformat() if team.tracking_start_date else "-"
        click.echo(
            f"{team.key:<14} "
            f"{('yes' if team.is_active else 'no'):<7} "
            f"{('yes' if _eligible(team, today) else 'no'):<9} "
            f"{board:<8} {start:<12} {team.name}"
        )
    click.echo(f"\n{len(teams)} team(s).")
