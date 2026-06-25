"""Generic natural-key upsert used by every ingester.

Jira payloads carry a stable external identifier (issue id, account id, board
id, ...) that maps to a unique column on our side. :func:`upsert` looks a row up
by that key, creates it when absent, and otherwise writes back only the fields
that actually changed — so re-running ingestion is idempotent and the
``updated`` counter reflects real changes rather than every row seen.
"""

from typing import Any

from tortoise.models import Model

from ingestion.sync.counters import SyncCounters


async def upsert(
    model: type[Model],
    *,
    natural_key: dict[str, Any],
    values: dict[str, Any],
    counters: SyncCounters | None = None,
) -> tuple[Model, bool]:
    """Create or update ``model`` identified by ``natural_key``.

    Returns ``(instance, created)``. When ``counters`` is provided, ``created``
    is incremented on insert and ``updated`` only when at least one field
    differed from the stored row.
    """
    instance = await model.get_or_none(**natural_key)

    if instance is None:
        instance = await model.create(**natural_key, **values)
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
