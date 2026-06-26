"""Runtime configuration for the Jira agile-delivery ingestion routine.

Settings are read from the environment (and an optional ``.env`` file) via
``pydantic-settings``, mirroring the convention used by the main Manager 360
application. Jira credentials and the database connection are therefore never
hard-coded in source.

The database can be configured two ways:

* a single ``DATABASE_URL`` in the same SQLAlchemy/ODBC form the main app uses
  (so the connection string can be copied verbatim between the two repos), or
* discrete ``DB_*`` fields, which are consulted only when ``DATABASE_URL`` is
  absent.

Either form is normalised into the credentials dict that Tortoise's MSSQL
backend expects via :attr:`AppSettings.tortoise_credentials`.
"""

from datetime import date
from functools import lru_cache
from urllib.parse import parse_qs, unquote, urlparse

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_ODBC_DRIVER = "ODBC Driver 18 for SQL Server"


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="allow"
    )

    # --- Database: single URL (preferred) or discrete fields ---------------
    database_url: str | None = None
    db_host: str | None = None
    db_port: int = 1433
    db_name: str | None = None
    db_user: str | None = None
    db_password: str | None = None
    db_driver: str = DEFAULT_ODBC_DRIVER

    # --- Jira ---------------------------------------------------------------
    jira_base_url: str
    jira_email: str
    jira_api_token: str
    jira_story_points_field: str = "customfield_10038"
    # Custom field holding the Epic Link (epic issue key) in classic projects.
    # Leave unset to skip epic linking (e.g. team-managed projects use parent).
    jira_epic_link_field: str | None = None

    # --- Jira client tuning -------------------------------------------------
    jira_page_size: int = 100
    jira_max_retries: int = 3
    jira_rate_limit_max_wait: float = 60.0
    jira_read_timeout: float = 60.0
    jira_connect_timeout: float = 30.0

    # --- Backfill -----------------------------------------------------------
    default_backfill_start_date: date | None = None

    # --- Logging ------------------------------------------------------------
    log_level: str = "INFO"
    log_dir: str | None = None

    @model_validator(mode="after")
    def _require_a_database(self) -> "AppSettings":
        if not self.database_url and not self.db_host:
            raise ValueError(
                "Database is not configured: set DATABASE_URL or the DB_* fields."
            )
        return self

    @property
    def tortoise_credentials(self) -> dict:
        """Credentials dict for ``tortoise.backends.mssql``."""
        if self.database_url:
            return _credentials_from_url(self.database_url)
        return {
            "host": self.db_host,
            "port": self.db_port,
            "user": self.db_user,
            "password": self.db_password,
            "database": self.db_name,
            "driver": self.db_driver,
        }


def _credentials_from_url(url: str) -> dict:
    """Parse a ``mssql+aioodbc://...`` SQLAlchemy URL into Tortoise credentials.

    Query parameters use ``+`` for spaces (e.g. ``ODBC+Driver+18+for+SQL+Server``);
    :func:`parse_qs` decodes those, while userinfo is percent-decoded explicitly.
    """
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    driver = query.get("driver", [DEFAULT_ODBC_DRIVER])[0]
    return {
        "host": parsed.hostname,
        "port": parsed.port or 1433,
        "user": unquote(parsed.username) if parsed.username else None,
        "password": unquote(parsed.password) if parsed.password else None,
        "database": parsed.path.lstrip("/") or None,
        "driver": driver,
    }


@lru_cache()
def get_app_settings() -> AppSettings:
    return AppSettings()  # type: ignore[call-arg]


settings = get_app_settings()
