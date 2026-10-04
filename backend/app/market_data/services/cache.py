"""Minimal in-memory TTL cache. Behind a small protocol so Redis can replace it later."""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Protocol


class Cache[K, V](Protocol):
    def get(self, key: K) -> V | None: ...

    def set(self, key: K, value: V, ttl: float | None = None) -> None: ...

    def delete(self, key: K) -> None: ...


class TTLCache[K, V]:
    def __init__(
        self,
        default_ttl: float,
        *,
        max_entries: int = 1024,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._default_ttl = default_ttl
        self._max_entries = max_entries
        self._clock = clock
        self._items: OrderedDict[K, tuple[float, V]] = OrderedDict()

    def get(self, key: K) -> V | None:
        entry = self._items.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if self._clock() >= expires_at:
            del self._items[key]
            return None
        self._items.move_to_end(key)
        return value

    def set(self, key: K, value: V, ttl: float | None = None) -> None:
        self._items[key] = (self._clock() + (ttl if ttl is not None else self._default_ttl), value)
        self._items.move_to_end(key)
        while len(self._items) > self._max_entries:
            self._items.popitem(last=False)

    def delete(self, key: K) -> None:
        self._items.pop(key, None)

    def __len__(self) -> int:
        return len(self._items)
