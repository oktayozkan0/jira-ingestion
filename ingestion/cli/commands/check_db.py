"""``check-db`` — verify the Tortoise MSSQL backend can reach Azure SQL.

This is the first thing to run on the scheduled-task machine: it confirms the
ODBC driver, credentials, and network path all work before any real ingestion
is attempted. It only issues a read-only ``SELECT`` and never touches schema.
"""

import asyncio

import click

from ingestion.db import CONNECTION_NAME, lifespan
from ingestion.logging_setup import configure_logging, get_logger

logger = get_logger(__name__)


async def _check_db() -> None:
    from tortoise import connections

    async with lifespan():
        conn = connections.get(CONNECTION_NAME)
        await conn.execute_query("SELECT 1")
        version_rows = await conn.execute_query_dict("SELECT @@VERSION AS version")
        version = version_rows[0]["version"] if version_rows else "unknown"
        logger.info("Database connectivity OK")
        logger.info("Server version: %s", str(version).splitlines()[0])


@click.command(name="check-db")
def check_db() -> None:
    """Check that the ingestion routine can connect to the database."""
    configure_logging()
    try:
        asyncio.run(_check_db())
    except Exception:
        logger.exception("Database connectivity check FAILED")
        raise SystemExit(1)
    click.echo("OK")
