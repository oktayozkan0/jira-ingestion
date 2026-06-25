from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, AsyncIterator, Iterable

if TYPE_CHECKING:
    from ingestion.atlassian.jira._jira import Jira


def _to_epoch_millis(value: datetime | int | float) -> int:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return int(value.timestamp() * 1000)
    return int(value)


def _chunked(items: list[Any], size: int):
    for i in range(0, len(items), size):
        yield items[i:i + size]


class Worklogs:
    """Read-only Jira Cloud worklog endpoints.

    This client intentionally exposes only retrieval operations — no add/update/
    delete — because we only generate reports over existing worklogs.

    See: https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issue-worklogs/
    """

    _BULK_FETCH_LIMIT = 1000

    def __init__(self, jira: "Jira"):
        self.jira: "Jira" = jira

    async def get_for_issue(
            self,
            issue_id_or_key: str,
            *,
            start_at: int = 0,
            max_results: int = 1048576,
            started_after: datetime | int | None = None,
            started_before: datetime | int | None = None,
            expand: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "startAt": start_at,
            "maxResults": max_results,
        }
        if started_after is not None:
            params["startedAfter"] = _to_epoch_millis(started_after)
        if started_before is not None:
            params["startedBefore"] = _to_epoch_millis(started_before)
        if expand:
            params["expand"] = expand
        return await self.jira._get(
            f"/rest/api/3/issue/{issue_id_or_key}/worklog",
            params=params,
        )

    async def iter_for_issue(
            self,
            issue_id_or_key: str,
            *,
            page_size: int = 1000,
            started_after: datetime | int | None = None,
            started_before: datetime | int | None = None,
            expand: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        start_at = 0
        while True:
            page = await self.get_for_issue(
                issue_id_or_key,
                start_at=start_at,
                max_results=page_size,
                started_after=started_after,
                started_before=started_before,
                expand=expand,
            )
            worklogs = page.get("worklogs") or []
            for w in worklogs:
                yield w
            total = page.get("total")
            start_at += len(worklogs)
            if not worklogs or (total is not None and start_at >= total):
                return

    async def get(self, issue_id_or_key: str, worklog_id: str | int) -> dict[str, Any]:
        return await self.jira._get(
            f"/rest/api/3/issue/{issue_id_or_key}/worklog/{worklog_id}"
        )

    async def updated_since(
            self,
            since: datetime | int,
            *,
            expand: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"since": _to_epoch_millis(since)}
        if expand:
            params["expand"] = expand
        return await self.jira._get("/rest/api/3/worklog/updated", params=params)

    async def deleted_since(self, since: datetime | int) -> dict[str, Any]:
        params = {"since": _to_epoch_millis(since)}
        return await self.jira._get("/rest/api/3/worklog/deleted", params=params)

    async def iter_updated_ids(self, since: datetime | int) -> AsyncIterator[int]:
        cursor = _to_epoch_millis(since)
        while True:
            page = await self.updated_since(cursor)
            values = page.get("values") or []
            for item in values:
                wid = item.get("worklogId")
                if wid is not None:
                    yield int(wid)
            if page.get("lastPage", True):
                return
            cursor = page.get("until")
            if cursor is None:
                return

    async def iter_deleted_ids(self, since: datetime | int) -> AsyncIterator[int]:
        cursor = _to_epoch_millis(since)
        while True:
            page = await self.deleted_since(cursor)
            values = page.get("values") or []
            for item in values:
                wid = item.get("worklogId")
                if wid is not None:
                    yield int(wid)
            if page.get("lastPage", True):
                return
            cursor = page.get("until")
            if cursor is None:
                return

    async def get_many(
            self,
            ids: Iterable[int | str],
            *,
            expand: str | None = None,
    ) -> list[dict[str, Any]]:
        """Bulk-fetch worklogs by ID. The endpoint is POST but read-only."""
        all_ids = list(ids)
        if not all_ids:
            return []
        results: list[dict[str, Any]] = []
        params = {"expand": expand} if expand else None
        for chunk in _chunked(all_ids, self._BULK_FETCH_LIMIT):
            payload = {"ids": [int(i) for i in chunk]}
            data = await self.jira._post(
                "/rest/api/3/worklog/list",
                json=payload,
                params=params,
            )
            if isinstance(data, list):
                results.extend(data)
        return results

    async def fetch_updated(
            self,
            since: datetime | int,
            *,
            expand: str | None = None,
    ) -> list[dict[str, Any]]:
        """Convenience: stream updated IDs then bulk-fetch the full worklog payloads."""
        ids: list[int] = []
        async for wid in self.iter_updated_ids(since):
            ids.append(wid)
        if not ids:
            return []
        return await self.get_many(ids, expand=expand)
