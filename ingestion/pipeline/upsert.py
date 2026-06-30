"""Generic natural-key upsert used by every ingester.

Jira payloads carry a stable external identifier (issue id, account id, board
id, ...) that maps to a unique column on our side. :func:`upsert` looks a row up
by that key, creates it when absent, and otherwise writes back only the fields
that actually changed — so re-running ingestion is idempotent and the
``updated`` counter reflects real changes rather than every row seen.
"""

from typing import Any, TypeVar

from tortoise.exceptions import IntegrityError
from tortoise.models import Model

from ingestion.sync.counters import SyncCounters

ModelT = TypeVar("ModelT", bound=Model)


async def upsert(
    model: type[ModelT],
    *,
    natural_key: dict[str, Any],
    values: dict[str, Any],
    create_only: dict[str, Any] | None = None,
    counters: SyncCounters | None = None,
) -> tuple[ModelT | None, bool]:
    """Create or update ``model`` identified by ``natural_key``.

    ``values`` are compared against the stored row and written back only when
    something differs. ``create_only`` fields are written on insert but never
    compared or updated afterwards — use them for provenance such as
    ``source_sync_run_id`` that would otherwise flag every row as changed each
    run merely because the run id moved.

    The lookup-then-insert is not atomic, and on some databases the initial read
    does not always see a row another connection just committed. So a duplicate
    insert is caught: the row is re-fetched and, if found, taken down the update
    path. If it still cannot be read, this returns ``(None, False)`` rather than
    crashing the run — callers treat a ``None`` instance as an unresolved
    reference (a null foreign key, or a skipped row) and carry on. Non-unique
    integrity errors (FK, NOT NULL, ...) are re-raised.

    Returns ``(instance_or_None, created)``. When ``counters`` is provided,
    ``created`` is incremented on insert and ``updated`` only when at least one
    ``values`` field differed from the stored row.
    """
    instance = await model.get_or_none(**natural_key)

    if instance is None:
        try:
            instance = await model.create(
                **natural_key, **values, **(create_only or {})
            )
        except IntegrityError as exc:
            if not _is_unique_violation(exc):
                # A different constraint (FK, NOT NULL, ...) — surface it.
                raise
            # The key exists but our read missed it. Re-read; if it still can't
            # be seen, degrade to (None, False) rather than crashing the run.
            instance = await model.get_or_none(**natural_key)
            if instance is None:
                return None, False
            # fall through to the update path with the row we found
        else:
            if counters is not None:
                counters.add(created=1)
            return instance, True

    changed = False
    for field, value in values.items():
        if getattr(instance, field) != value:
            setattr(instance, field, value)
            changed = True
    if changed:
        await instance.save()
        if counters is not None:
            counters.add(updated=1)
    return instance, False


def _is_unique_violation(exc: Exception) -> bool:
    message = str(exc).lower()
    return "unique" in message or "duplicate key" in message


async def insert_or_ignore(
    model: type[ModelT],
    *,
    natural_key: dict[str, Any],
    values: dict[str, Any],
    create_only: dict[str, Any] | None = None,
    counters: SyncCounters | None = None,
) -> bool:
    """Insert a row for an immutable, append-only fact; ignore it if present.

    Unlike :func:`upsert`, this never depends on the lookup succeeding. If the
    natural key already exists but the lookup did not see it (a stale read on a
    pooled connection), the insert's unique-constraint violation is caught and
    treated as "already present" rather than crashing the run. Non-unique
    integrity errors (FK, NOT NULL, ...) are re-raised. Returns True if a row
    was inserted.
    """
    if await model.filter(**natural_key).exists():
        return False
    try:
        await model.create(**natural_key, **values, **(create_only or {}))
    except IntegrityError as exc:
        if _is_unique_violation(exc):
            return False
        raise
    if counters is not None:
        counters.add(created=1)
    return True
