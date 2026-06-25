"""Ingesters for the global Jira reference dimensions.

Issue types, statuses and priorities are small, site-wide sets that issues refer
to by id. Each is fetched in full and upserted under its own ``jira_sync_runs``
audit row. They are team-agnostic, so the runs carry no ``team_id``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ingestion.enums import JiraSyncEntityType, JiraSyncTrigger
from ingestion.models import JiraIssueType, JiraPriority, JiraStatus
from ingestion.pipeline.upsert import upsert
from ingestion.sync import sync_run

if TYPE_CHECKING:
    from ingestion.atlassian.jira import Jira


async def ingest_issue_types(
    jira: "Jira", *, triggered_by: JiraSyncTrigger = JiraSyncTrigger.SCHEDULED
) -> None:
    async with sync_run(
        JiraSyncEntityType.ISSUE_TYPES, triggered_by=triggered_by
    ) as ctx:
        for item in (await jira.metadata.issue_types()) or []:
            ctx.counters.add(fetched=1)
            await upsert(
                JiraIssueType,
                natural_key={"jira_issue_type_id": str(item["id"])},
                values={
                    "name": item.get("name") or "",
                    "is_subtask": bool(item.get("subtask", False)),
                    "icon_url": item.get("iconUrl"),
                },
                counters=ctx.counters,
            )


async def ingest_statuses(
    jira: "Jira", *, triggered_by: JiraSyncTrigger = JiraSyncTrigger.SCHEDULED
) -> None:
    async with sync_run(JiraSyncEntityType.STATUSES, triggered_by=triggered_by) as ctx:
        for item in (await jira.metadata.statuses()) or []:
            ctx.counters.add(fetched=1)
            category = item.get("statusCategory") or {}
            await upsert(
                JiraStatus,
                natural_key={"jira_status_id": str(item["id"])},
                values={
                    "name": item.get("name") or "",
                    "status_category_key": category.get("key") or "",
                    "status_category_name": category.get("name"),
                },
                counters=ctx.counters,
            )


async def ingest_priorities(
    jira: "Jira", *, triggered_by: JiraSyncTrigger = JiraSyncTrigger.SCHEDULED
) -> None:
    async with sync_run(
        JiraSyncEntityType.PRIORITIES, triggered_by=triggered_by
    ) as ctx:
        for item in (await jira.metadata.priorities()) or []:
            ctx.counters.add(fetched=1)
            await upsert(
                JiraPriority,
                natural_key={"jira_priority_id": str(item["id"])},
                values={
                    "name": item.get("name") or "",
                    "icon_url": item.get("iconUrl"),
                },
                counters=ctx.counters,
            )
