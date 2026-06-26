"""Sprint membership derivation (-> ``jira_sprint_issues``).

Each row records one window an issue spent in a sprint. ``added_at`` /
``removed_at`` are reconstructed from the issue's "Sprint" field changelog
transitions; sprints the issue currently belongs to but has no add transition
for (it was created in the sprint, or the changelog was truncated) are recorded
from the issue's creation time. The ``committed`` / ``added_during_sprint`` /
``completed_in_sprint`` flags and the story-point snapshots are deliberately
left at their defaults — they are derived metrics, computed by a separate task.

Windows are keyed on ``(sprint_id, issue_id, added_at)``: re-running finds the
same window by its start time and only updates ``removed_at`` when an issue
later leaves the sprint, so ingestion stays idempotent without a unique
constraint on the table.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any

from ingestion.config import settings
from ingestion.models import JiraIssue, JiraSprint, JiraSprintIssue
from ingestion.pipeline.parsing import parse_jira_datetime
from ingestion.pipeline.upsert import upsert
from ingestion.sync.counters import SyncCounters

logger = logging.getLogger(__name__)

# Legacy Jira encodes sprints as "...Sprint@x[id=1,rapidViewId=2,...]".
_LEGACY_SPRINT_ID = re.compile(r"id=(\d+)")

# (sprint jira id, added_at, removed_at)
Window = tuple[int, datetime, datetime | None]


def _parse_sprint_ids(raw: str | None) -> list[int]:
    """Sprint changelog ``from``/``to`` are comma-separated sprint ids."""
    if not raw:
        return []
    ids: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            ids.append(int(part))
    return ids


def _current_sprint_ids(issue: dict[str, Any]) -> list[int]:
    value = (issue.get("fields") or {}).get(settings.jira_sprint_field)
    if not isinstance(value, list):
        return []
    ids: list[int] = []
    for entry in value:
        if isinstance(entry, dict) and entry.get("id") is not None:
            ids.append(int(entry["id"]))
        elif isinstance(entry, str):
            match = _LEGACY_SPRINT_ID.search(entry)
            if match:
                ids.append(int(match.group(1)))
    return ids


def _membership_windows(
    histories: list[dict[str, Any]],
    created_at: datetime,
    current_ids: list[int],
) -> list[Window]:
    transitions: list[tuple[datetime, set[int], set[int]]] = []
    for history in histories:
        changed_at = parse_jira_datetime(history.get("created"))
        if changed_at is None:
            continue
        for item in history.get("items") or []:
            if (item.get("field") or "").lower() != "sprint":
                continue
            from_ids = set(_parse_sprint_ids(item.get("from")))
            to_ids = set(_parse_sprint_ids(item.get("to")))
            transitions.append((changed_at, to_ids - from_ids, from_ids - to_ids))
    transitions.sort(key=lambda t: t[0])

    open_windows: dict[int, datetime] = {}
    windows: list[Window] = []
    for changed_at, added, removed in transitions:
        for sid in added:
            open_windows[sid] = changed_at
        for sid in removed:
            start = open_windows.pop(sid, created_at)
            windows.append((sid, start, changed_at))
    for sid, start in open_windows.items():
        windows.append((sid, start, None))

    windowed = {sid for sid, _, _ in windows}
    for sid in current_ids:
        if sid not in windowed:
            windows.append((sid, created_at, None))
    return windows


async def ingest_sprint_membership(
    issue: dict[str, Any],
    issue_row: JiraIssue,
    histories: list[dict[str, Any]],
    counters: SyncCounters,
) -> None:
    """Upsert the issue's sprint membership windows for tracked sprints."""
    windows = _membership_windows(
        histories, issue_row.jira_created_at, _current_sprint_ids(issue)
    )
    for sprint_jira_id, added_at, removed_at in windows:
        sprint = await JiraSprint.get_or_none(jira_sprint_id=sprint_jira_id)
        if sprint is None:
            # Sprint not tracked/ingested yet; skip rather than orphan the row.
            continue
        await upsert(
            JiraSprintIssue,
            natural_key={
                "sprint_id": sprint.id,
                "issue_id": issue_row.id,
                "added_at": added_at,
            },
            values={"removed_at": removed_at},
            counters=counters,
        )
