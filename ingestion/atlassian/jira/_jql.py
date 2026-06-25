"""JQL query builder helpers.

These helpers focus on safe value quoting and the most common predicates used
when building queries. JQL is large; this is intentionally minimal.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Iterable


def quote(value: str) -> str:
    """Quote a JQL string value, escaping internal quotes and backslashes."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _fmt_date(value: date | datetime | str) -> str:
    if isinstance(value, datetime):
        return quote(value.strftime("%Y-%m-%d %H:%M"))
    if isinstance(value, date):
        return quote(value.strftime("%Y-%m-%d"))
    return quote(str(value))


def in_clause(field: str, values: Iterable[str]) -> str:
    items = ", ".join(quote(v) for v in values)
    return f"{field} in ({items})"


def worklog_author(account_ids: Iterable[str]) -> str:
    return in_clause("worklogAuthor", account_ids)


def worklog_date_between(
        start: date | datetime | str,
        end: date | datetime | str,
) -> str:
    return f"worklogDate >= {_fmt_date(start)} AND worklogDate <= {_fmt_date(end)}"


def project_in(keys: Iterable[str]) -> str:
    return in_clause("project", keys)


def updated_since(value: date | datetime | str) -> str:
    return f"updated >= {_fmt_date(value)}"


def and_(*clauses: str) -> str:
    parts = [c for c in clauses if c]
    return " AND ".join(f"({c})" for c in parts)


def or_(*clauses: str) -> str:
    parts = [c for c in clauses if c]
    return " OR ".join(f"({c})" for c in parts)
