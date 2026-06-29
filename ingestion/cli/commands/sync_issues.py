"""``sync-issues`` — ingest one team's issues (incremental or backfill).

A single-team entry point for development and ad-hoc operations; the scheduled
all-teams orchestration is a separate command. The searching account's timezone
is fetched so JQL ``updated`` literals are compared in the right zone.
"""

import asyncio

import click

from ingestion.db import lifespan
from ingestion.jira_client import build_jira
from ingestion.logging_setup import configure_logging, get_logger
from ingestion.models import TrackedJiraTeam
from ingestion.pipeline import ingest_issues_for_team, resolve_account_timezone
from ingestion.pipeline.dedupe import reset_dedupe

logger = get_logger(__name__)


async def _run(team_key: str, backfill: bool) -> None:
    reset_dedupe()
    async with lifespan(), build_jira() as jira:
        team = await TrackedJiraTeam.get_or_none(key=team_key)
        if team is None:
            raise click.ClickException(f"No tracked team with key {team_key!r}")
        me = await jira.get_myself()
        tz = resolve_account_timezone(me.get("timeZone"))
        await ingest_issues_for_team(
            jira,
            team,
            mode="backfill" if backfill else "incremental",
            jira_timezone=tz,
        )


@click.command(name="sync-issues")
@click.option(
    "--team", "team_key", required=True, help="Tracked team key (Jira project key)."
)
@click.option(
    "--backfill",
    is_flag=True,
    default=False,
    help="Backfill from the team's start date instead of the incremental watermark.",
)
def sync_issues(team_key: str, backfill: bool) -> None:
    """Ingest issues for one tracked team."""
    configure_logging()
    try:
        asyncio.run(_run(team_key, backfill))
    except click.ClickException:
        raise
    except Exception:
        logger.exception("Issue sync FAILED for team %s", team_key)
        raise SystemExit(1)
    click.echo("OK")
