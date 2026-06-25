from __future__ import annotations

from typing import TYPE_CHECKING, Any, AsyncIterator

if TYPE_CHECKING:
    from ingestion.atlassian.jira._jira import Jira


class Projects:
    """Read-only Jira Cloud project endpoints."""

    def __init__(self, jira: "Jira"):
        self.jira: "Jira" = jira

    async def get(self, project_id_or_key: str, *, expand: str | None = None) -> dict[str, Any]:
        params = {"expand": expand} if expand else None
        return await self.jira._get(
            f"/rest/api/3/project/{project_id_or_key}",
            params=params,
        )

    async def search(
            self,
            *,
            query: str | None = None,
            start_at: int = 0,
            max_results: int = 50,
            order_by: str | None = None,
            type_key: str | None = None,
            status: str | None = None,
            expand: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"startAt": start_at, "maxResults": max_results}
        if query:
            params["query"] = query
        if order_by:
            params["orderBy"] = order_by
        if type_key:
            params["typeKey"] = type_key
        if status:
            params["status"] = status
        if expand:
            params["expand"] = expand
        return await self.jira._get("/rest/api/3/project/search", params=params)

    async def iter_all(self, *, page_size: int = 50, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        start_at = 0
        while True:
            page = await self.search(start_at=start_at, max_results=page_size, **kwargs)
            values = page.get("values") or []
            for project in values:
                yield project
            if page.get("isLast", True) or not values:
                return
            start_at += len(values)
