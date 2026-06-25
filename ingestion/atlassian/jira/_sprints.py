from __future__ import annotations

from typing import TYPE_CHECKING, Any, AsyncIterator, Iterable

if TYPE_CHECKING:
    from ingestion.atlassian.jira._jira import Jira

_AGILE = "/rest/agile/1.0"


class Sprints:
    """Read-only Jira Agile (Software) sprint endpoints.

    Sprints belong to a (Scrum) board; their issues carry the membership and
    story-point data the Delivery 360 metrics are built from. Pagination follows
    the ``startAt`` / ``isLast`` style for sprint listings and the
    ``startAt`` / ``total`` style for sprint issues.

    See: https://developer.atlassian.com/cloud/jira/software/rest/api-group-sprint/
    """

    def __init__(self, jira: "Jira"):
        self.jira: "Jira" = jira

    async def get(self, sprint_id: int | str) -> dict[str, Any]:
        return await self.jira._get(f"{_AGILE}/sprint/{sprint_id}")

    async def list_for_board(
            self,
            board_id: int | str,
            *,
            start_at: int = 0,
            max_results: int = 50,
            state: str | None = None,
    ) -> dict[str, Any]:
        """List sprints on a board. ``state`` may be a comma-separated subset of
        ``future,active,closed``."""
        params: dict[str, Any] = {"startAt": start_at, "maxResults": max_results}
        if state:
            params["state"] = state
        return await self.jira._get(
            f"{_AGILE}/board/{board_id}/sprint", params=params
        )

    async def iter_for_board(
            self,
            board_id: int | str,
            *,
            state: str | None = None,
            page_size: int = 50,
    ) -> AsyncIterator[dict[str, Any]]:
        start_at = 0
        while True:
            page = await self.list_for_board(
                board_id,
                start_at=start_at,
                max_results=page_size,
                state=state,
            )
            values = page.get("values") or []
            for sprint in values:
                yield sprint
            if page.get("isLast", True) or not values:
                return
            start_at += len(values)

    async def issues(
            self,
            sprint_id: int | str,
            *,
            start_at: int = 0,
            max_results: int = 50,
            jql: str | None = None,
            fields: Iterable[str] | str | None = None,
            expand: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"startAt": start_at, "maxResults": max_results}
        if jql:
            params["jql"] = jql
        if fields is not None:
            params["fields"] = _csv(fields)
        if expand:
            params["expand"] = expand
        return await self.jira._get(
            f"{_AGILE}/sprint/{sprint_id}/issue", params=params
        )

    async def iter_issues(
            self,
            sprint_id: int | str,
            *,
            page_size: int = 100,
            jql: str | None = None,
            fields: Iterable[str] | str | None = None,
            expand: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        start_at = 0
        while True:
            page = await self.issues(
                sprint_id,
                start_at=start_at,
                max_results=page_size,
                jql=jql,
                fields=fields,
                expand=expand,
            )
            issues = page.get("issues") or []
            for issue in issues:
                yield issue
            total = page.get("total")
            start_at += len(issues)
            if not issues or (total is not None and start_at >= total):
                return


def _csv(value: Iterable[str] | str) -> str:
    if isinstance(value, str):
        return value
    return ",".join(value)
