"""Per-run de-duplication of get-or-create resolutions.

Within one run the same external id — a user ``accountId``, an issue-type /
status / priority id, a board or sprint id — is referenced by many issues.
Resolving each through the database every time is wasteful and, more seriously,
the source of unique-key collisions: the lookup-then-insert in :func:`upsert` is
not atomic, so a key created earlier in the run can be inserted again before the
prior write is observed, tripping the unique constraint.

:func:`once` resolves each ``(namespace, key)`` at most once per run. The first
caller runs the factory (the upsert) under a per-key lock and caches the result;
concurrent or later callers await the lock and receive the cached value, so the
id is created exactly once. Call :func:`reset_dedupe` at the start of every run
so a long-lived process does not carry stale state between runs.
"""

import asyncio
from collections.abc import Awaitable, Callable, Hashable
from typing import TypeVar, cast

T = TypeVar("T")

_caches: dict[str, dict[Hashable, object]] = {}
_locks: dict[str, dict[Hashable, asyncio.Lock]] = {}


def reset_dedupe() -> None:
    """Clear all cached resolutions. Call once at the start of a run."""
    _caches.clear()
    _locks.clear()


async def once(
    namespace: str, key: Hashable, factory: Callable[[], Awaitable[T]]
) -> T:
    """Resolve ``key`` within ``namespace`` exactly once per run.

    On the first call the factory runs under a per-key lock and its result is
    cached; subsequent calls (including ones that arrive while the factory is
    still running) return the cached result without touching the database.
    """
    cache = _caches.setdefault(namespace, {})
    if key in cache:
        return cast(T, cache[key])
    lock = _locks.setdefault(namespace, {}).setdefault(key, asyncio.Lock())
    async with lock:
        if key in cache:
            return cast(T, cache[key])
        result = await factory()
        cache[key] = result
        return result
