"""On-demand resolution of Jira users embedded in issue payloads.

Issues carry full user objects for assignee / reporter / creator, so users are
upserted as those objects are encountered rather than bulk-pulling every account
on the site (most of which never touch a tracked team's issues). The whole
payload is retained in ``raw_payload`` for later enrichment.
"""

from __future__ import annotations

from typing import Any

from ingestion.models import JiraUser
from ingestion.pipeline.upsert import upsert
from ingestion.sync.counters import SyncCounters


def _primary_avatar(payload: dict[str, Any]) -> str | None:
    avatars = payload.get("avatarUrls") or {}
    return avatars.get("48x48") or next(iter(avatars.values()), None)


async def resolve_user(
    payload: dict[str, Any] | None,
    *,
    counters: SyncCounters | None = None,
) -> JiraUser | None:
    """Upsert and return the user described by an embedded Jira user object.

    Returns None when the payload is missing or has no ``accountId`` (e.g. an
    unassigned field), so callers can pass the result straight into a nullable
    foreign key.
    """
    if not payload:
        return None
    account_id = payload.get("accountId")
    if not account_id:
        return None

    user, _ = await upsert(
        JiraUser,
        natural_key={"account_id": account_id},
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
