"""On-demand resolution of Jira users embedded in issue payloads.

Issues carry full user objects for assignee / reporter / creator, so users are
upserted as those objects are encountered rather than bulk-pulling every account
on the site (most of which never touch a tracked team's issues). The whole
payload is retained in ``raw_payload`` for later enrichment.
"""

from __future__ import annotations

from functools import partial
from typing import Any

from ingestion.models import JiraUser
from ingestion.pipeline.dedupe import once
from ingestion.pipeline.upsert import upsert
from ingestion.sync.counters import SyncCounters


def _primary_avatar(payload: dict[str, Any]) -> str | None:
    avatars = payload.get("avatarUrls") or {}
    return avatars.get("48x48") or next(iter(avatars.values()), None)


async def _upsert_user(
    payload: dict[str, Any], counters: SyncCounters | None
) -> JiraUser | None:
    user, _ = await upsert(
        JiraUser,
        natural_key={"account_id": payload["accountId"]},
        values={
            "display_name": payload.get("displayName"),
            "email_address": payload.get("emailAddress"),
            "is_active": bool(payload.get("active", True)),
            "timezone": payload.get("timeZone"),
            "avatar_url": _primary_avatar(payload),
            "raw_payload": payload,
        },
        counters=counters,
    )
    return user


async def resolve_user(
    payload: dict[str, Any] | None,
    *,
    counters: SyncCounters | None = None,
) -> JiraUser | None:
    """Upsert and return the user described by an embedded Jira user object.

    Each ``accountId`` is resolved at most once per run (see :func:`once`), so
    the same user referenced across many issues is inserted exactly once.
    Returns None when the payload is missing or has no ``accountId`` (e.g. an
    unassigned field), so callers can pass the result straight into a nullable
    foreign key.
    """
    if not payload:
        return None
    account_id = payload.get("accountId")
    if not account_id:
        return None
    return await once("users", account_id, partial(_upsert_user, payload, counters))
