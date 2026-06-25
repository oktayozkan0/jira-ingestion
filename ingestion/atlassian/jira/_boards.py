from __future__ import annotations

from typing import TYPE_CHECKING, Any, AsyncIterator

if TYPE_CHECKING:
    from ingestion.atlassian.jira._jira import Jira

_AGILE = "/rest/agile/1.0"


class Boards:
    """Read-only Jira Agile (Software) board endpoints.

    These live under ``/rest/agile/1.0`` rather than the platform ``/rest/api/3``
    namespace and are required for sprint metrics, which the platform API does
    not expose. Pagination here uses the classic ``startAt`` / ``isLast`` style.

    See: https://developer.atlassian.com/cloud/jira/software/rest/api-group-board/
    """

    def __init__(self, jira: "Jira"):
        self.jira: "Jira" = jira

    async def get(self, board_id: int | str) -> dict[str, Any]:
        return await self.jira._get(f"{_AGILE}/board/{board_id}")

    async def search(
            self,
            *,
            start_at: int = 0,
            max_results: int = 50,
            board_type: str | None = None,
            name: str | None = None,
            project_key_or_id: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"startAt": start_at, "maxResults": max_results}
        if board_type:
            params["type"] = board_type
        if name:
            params["name"] = name
        if project_key_or_id:
            params["projectKeyOrId"] = project_key_or_id
        return await self.jira._get(f"{_AGILE}/board", params=params)

    async def iter_all(
            self,
            *,
            page_size: int = 50,
            **kwargs: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        start_at = 0
        while True:
            page = await self.search(
                start_at=start_at, max_results=page_size, **kwargs
            )
            values = page.get("values") or []
            for board in values:
                yield board
            if page.get("isLast", True) or not values:
                return
            start_at += len(values)

    async def get_configuration(self, board_id: int | str) -> dict[str, Any]:
        """Board configuration, including the estimation (story points) field."""
        return await self.jira._get(f"{_AGILE}/board/{board_id}/configuration")
