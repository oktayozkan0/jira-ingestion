from __future__ import annotations

from typing import TYPE_CHECKING, Any, AsyncIterator

if TYPE_CHECKING:
    from ingestion.atlassian.jira._jira import Jira


class Users:
    """Read-only Jira Cloud user endpoints.

    Used to resolve `accountId` values into human-friendly display names / emails.
    """

    def __init__(self, jira: "Jira"):
        self.jira: "Jira" = jira

    async def get(
            self,
            *,
            account_id: str | None = None,
            username: str | None = None,
            key: str | None = None,
            expand: str | None = None,
    ) -> dict[str, Any]:
        if not any([account_id, username, key]):
            raise ValueError("One of account_id, username or key must be provided.")
        params: dict[str, Any] = {}
        if account_id:
            params["accountId"] = account_id
        if username:
            params["username"] = username
        if key:
            params["key"] = key
        if expand:
            params["expand"] = expand
        return await self.jira._get("/rest/api/3/user", params=params)

    async def search(
            self,
            query: str | None = None,
            *,
            account_id: str | None = None,
            start_at: int = 0,
            max_results: int = 50,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"startAt": start_at, "maxResults": max_results}
        if query is not None:
            params["query"] = query
        if account_id:
            params["accountId"] = account_id
        return await self.jira._get("/rest/api/3/user/search", params=params)

    async def list_all(
            self,
            *,
            start_at: int = 0,
            max_results: int = 50,
    ) -> list[dict[str, Any]]:
        params = {"startAt": start_at, "maxResults": max_results}
        return await self.jira._get("/rest/api/3/users/search", params=params)

    async def iter_all(self, *, page_size: int = 200) -> AsyncIterator[dict[str, Any]]:
        start_at = 0
        while True:
            page = await self.list_all(start_at=start_at, max_results=page_size)
            if not page:
                return
            for user in page:
                yield user
            if len(page) < page_size:
                return
            start_at += len(page)
