"""On-demand resolution of reference dimensions embedded in issue payloads.

An issue carries its full issue-type / status / priority objects, so these
resolvers upsert the dimension and return its internal id for the issue's
foreign key — mirroring :func:`ingestion.pipeline.users.resolve_user`. They make
issue ingestion self-sufficient even if the bulk dimension sync has not run, and
stay consistent with the bulk ingesters' field mapping.
"""

from __future__ import annotations

from typing import Any

from ingestion.models import JiraIssueType, JiraPriority, JiraStatus
from ingestion.pipeline.upsert import upsert
from ingestion.sync.counters import SyncCounters


async def resolve_issue_type(
    payload: dict[str, Any] | None, *, counters: SyncCounters | None = None
) -> int | None:
    if not payload or payload.get("id") is None:
        return None
    obj, _ = await upsert(
        JiraIssueType,
        natural_key={"jira_issue_type_id": str(payload["id"])},
        values={
            "name": payload.get("name") or "",
            "is_subtask": bool(payload.get("subtask", False)),
            "icon_url": payload.get("iconUrl"),
        },
        counters=counters,
    )
    return obj.id


async def resolve_status(
    payload: dict[str, Any] | None, *, counters: SyncCounters | None = None
) -> int | None:
    if not payload or payload.get("id") is None:
        return None
    category = payload.get("statusCategory") or {}
    obj, _ = await upsert(
        JiraStatus,
        natural_key={"jira_status_id": str(payload["id"])},
        values={
            "name": payload.get("name") or "",
            "status_category_key": category.get("key") or "",
            "status_category_name": category.get("name"),
        },
        counters=counters,
    )
    return obj.id


async def resolve_priority(
    payload: dict[str, Any] | None, *, counters: SyncCounters | None = None
) -> int | None:
    if not payload or payload.get("id") is None:
        return None
    obj, _ = await upsert(
        JiraPriority,
        natural_key={"jira_priority_id": str(payload["id"])},
        values={
            "name": payload.get("name") or "",
            "icon_url": payload.get("iconUrl"),
        },
        counters=counters,
    )
    return obj.id
