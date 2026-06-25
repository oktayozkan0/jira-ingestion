"""Volume counters accumulated during a single sync run.

The counts are surfaced two ways: persisted onto the ``jira_sync_runs`` audit
row, and rendered into the run's log line — together satisfying the task's
"logs ... data volume" requirement.
"""

from dataclasses import dataclass


@dataclass
class SyncCounters:
    fetched: int = 0
    created: int = 0
    updated: int = 0
    deleted: int = 0
    failed: int = 0

    def add(
        self,
        *,
        fetched: int = 0,
        created: int = 0,
        updated: int = 0,
        deleted: int = 0,
        failed: int = 0,
    ) -> None:
        self.fetched += fetched
        self.created += created
        self.updated += updated
        self.deleted += deleted
        self.failed += failed

    @property
    def total(self) -> int:
        """Rows touched (created + updated + deleted)."""
        return self.created + self.updated + self.deleted

    def summary(self) -> str:
        return (
            f"fetched={self.fetched} created={self.created} "
            f"updated={self.updated} deleted={self.deleted} failed={self.failed}"
        )
