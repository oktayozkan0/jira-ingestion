"""Parsing helpers for Jira timestamp/date strings.

Jira returns datetimes as ISO 8601 with millisecond precision and either a ``Z``
or numeric offset (e.g. ``2026-01-01T10:00:00.000Z``). Everything is normalised
to timezone-aware UTC so it round-trips cleanly through the ``DATETIMEOFFSET``
columns (Tortoise is initialised with ``use_tz=True``). Date-only fields such as
``duedate`` come back as ``YYYY-MM-DD``.
"""

from datetime import date, datetime, timezone


def parse_jira_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_jira_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None
