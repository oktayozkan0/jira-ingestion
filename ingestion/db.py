"""Tortoise ORM bootstrap for the ingestion routine.

The ingestion repo does **not** own the database schema: the tables are created
and migrated by the main Manager 360 application (SQLAlchemy + Alembic). Tortoise
here only *maps* the already-existing tables, so schema generation is never
invoked (``generate_schemas`` is intentionally not called anywhere).

``MODELS_MODULES`` lists the modules Tortoise scans for models. It is empty for
now and gets populated once the mapped models land in a later commit.
"""

from contextlib import asynccontextmanager

from tortoise import Tortoise, connections

from ingestion.config import settings

MODELS_MODULES: list[str] = ["ingestion.models"]

APP_LABEL = "models"
CONNECTION_NAME = "default"


def get_tortoise_config() -> dict:
    return {
        "connections": {
            CONNECTION_NAME: {
                "engine": "tortoise.backends.mssql",
                "credentials": settings.tortoise_credentials,
            }
        },
        "apps": {
            APP_LABEL: {
                "models": MODELS_MODULES,
                "default_connection": CONNECTION_NAME,
            }
        },
    }


async def init_db() -> None:
    """Open the connection pool and register mapped models. No schema is created.

    ``use_tz=True`` keeps datetimes timezone-aware so they round-trip through the
    ``DATETIMEOFFSET`` columns the main app created from ``DateTime(timezone=True)``.
    """
    await Tortoise.init(config=get_tortoise_config(), use_tz=True, timezone="UTC")


async def close_db() -> None:
    await connections.close_all()


@asynccontextmanager
async def lifespan():
    """Async context manager that opens and reliably closes the DB connection."""
    await init_db()
    try:
        yield
    finally:
        await close_db()
