"""``sync`` — the scheduled all-teams ingestion entry point.

This is the command the Windows scheduled task runs (2-4x/day). It ingests the
global dimensions and every active configured team. Exit codes let the scheduler
distinguish outcomes: 0 = clean, 2 = completed but some scopes failed, 1 = the
run could not start / crashed.
"""

import asyncio

import click

from ingestion.db import lifespan
from ingestion.enums import JiraSyncTrigger
from ingestion.jira_client import build_jira
from ingestion.logging_setup import configure_logging, get_logger
from ingestion.orchestrator import RunSummary, run_ingestion
from ingestion.pipeline import IngestMode

logger = get_logger(__name__)


async def _run(mode: IngestMode, team_keys: list[str] | None) -> RunSummary:
    async with lifespan(), build_jira() as jira:
        return await run_ingestion(
            jira,
            mode=mode,
            team_keys=team_keys,
            triggered_by=JiraSyncTrigger.SCHEDULED,
        )


@click.command(name="sync")
@click.option(
    "--backfill",
    is_flag=True,
    default=False,
    help="Backfill issues from each team's start date instead of the watermark.",
)
@click.option(
    "--team",
    "team_keys",
    multiple=True,
    help="Limit the run to specific team key(s). Repeatable; default is all.",
)
def sync(backfill: bool, team_keys: tuple[str, ...]) -> None:
    """Ingest Jira data for all active configured teams."""
    configure_logging()
    mode: IngestMode = "backfill" if backfill else "incremental"
    try:
        summary = asyncio.run(_run(mode, list(team_keys) or None))
    except Exception:
        logger.exception("Ingestion run FAILED to complete")
        raise SystemExit(1)

    if summary.ok:
        click.echo(f"OK ({summary.teams_total} teams, {summary.duration_seconds:.0f}s)")
        raise SystemExit(0)
    click.echo(
        f"COMPLETED WITH FAILURES ({len(summary.failures)} scope(s)): "
        + ", ".join(f"{scope}/{entity}" for scope, entity in summary.failures)
    )
    raise SystemExit(2)
