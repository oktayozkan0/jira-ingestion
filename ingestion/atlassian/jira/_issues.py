from __future__ import annotations

from typing import TYPE_CHECKING, Any, AsyncIterator, Iterable

if TYPE_CHECKING:
    from ingestion.atlassian.jira._jira import Jira


class Issues:
    """Read-only Jira Cloud issue endpoints."""

    def __init__(self, jira: "Jira"):
        self.jira: "Jira" = jira

    async def get(
            self,
            issue_id_or_key: str,
            *,
            fields: Iterable[str] | str | None = None,
            expand: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if fields is not None:
            params["fields"] = _csv(fields)
        if expand:
            params["expand"] = expand
        return await self.jira._get(
            f"/rest/api/3/issue/{issue_id_or_key}",
            params=params or None,
        )

    # Backwards-compatible alias.
    async def get_issue(self, issue_id: str) -> dict[str, Any]:
        return await self.get(issue_id)

    async def search(
            self,
            jql: str,
            *,
            max_results: int = 50,
            next_page_token: str | None = None,
            fields: Iterable[str] | str | None = None,
            expand: str | None = None,
    ) -> dict[str, Any]:
        """Token-based search (Jira Cloud `/rest/api/3/search/jql`).

        Returns a page containing `issues` and an optional `nextPageToken`.
        """
        body: dict[str, Any] = {"jql": jql, "maxResults": max_results}
        if next_page_token:
            body["nextPageToken"] = next_page_token
        if fields is not None:
            body["fields"] = _as_list(fields)
        if expand:
            body["expand"] = expand
        return await self.jira._post("/rest/api/3/search/jql", json=body)

    async def iter_search(
            self,
            jql: str,
            *,
            page_size: int = 100,
            fields: Iterable[str] | str | None = None,
            expand: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        token: str | None = None
        while True:
            page = await self.search(
                jql,
                max_results=page_size,
                next_page_token=token,
                fields=fields,
                expand=expand,
            )
            issues = page.get("issues") or []
            for issue in issues:
                yield issue
            token = page.get("nextPageToken")
            if not token or not issues:
                return


def _csv(value: Iterable[str] | str) -> str:
    if isinstance(value, str):
        return value
    return ",".join(value)


def _as_list(value: Iterable[str] | str) -> list[str]:
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    return list(value)
