from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ingestion.atlassian.jira._jira import Jira


class Metadata:
    """Read-only Jira reference data: issue types, statuses, priorities.

    Each endpoint returns the full set in a single (unpaginated) response, which
    is appropriate for these small, slowly-changing global dimensions.
    """

    def __init__(self, jira: "Jira"):
        self.jira: "Jira" = jira

    async def issue_types(self) -> list[dict[str, Any]]:
        return await self.jira._get("/rest/api/3/issuetype")

    async def statuses(self) -> list[dict[str, Any]]:
        return await self.jira._get("/rest/api/3/status")

    async def priorities(self) -> list[dict[str, Any]]:
        return await self.jira._get("/rest/api/3/priority")
