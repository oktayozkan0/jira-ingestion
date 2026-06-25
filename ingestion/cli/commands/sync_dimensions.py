"""``sync-dimensions`` — ingest global Jira reference data.

Exercises the full stack end to end (Jira API -> Tortoise -> Azure SQL) for the
simplest, team-agnostic entities, which makes it a good smoke test of both Jira
authentication and the database write path before team-scoped ingestion runs.
"""

import asyncio

import click

from ingestion.db import lifespan
from ingestion.jira_client import build_jira
from ingestion.logging_setup import configure_logging, get_logger
from ingestion.pipeline import (
    ingest_issue_types,
    ingest_priorities,
    ingest_statuses,
)

logger = get_logger(__name__)


async def _run() -> None:
    async with lifespan(), build_jira() as jira:
        await ingest_issue_types(jira)
        await ingest_statuses(jira)
        await ingest_priorities(jira)


@click.command(name="sync-dimensions")
def sync_dimensions() -> None:
    """Ingest Jira reference dimensions (issue types, statuses, priorities)."""
    configure_logging()
    try:
        asyncio.run(_run())
    except Exception:
        logger.exception("Dimension sync FAILED")
        raise SystemExit(1)
    click.echo("OK")
