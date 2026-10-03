"""Simple in-memory login throttling (per username and per client address).

Sufficient for a single-process local deployment. A multi-instance deployment should move
this to a shared store (e.g. Redis) behind the same interface.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field


@dataclass
class LoginRateLimiter:
    max_failures: int = 5
    window_seconds: float = 300.0
    _failures: dict[str, deque[float]] = field(default_factory=dict)

    def _prune(self, key: str, now: float) -> deque[float]:
        bucket = self._failures.setdefault(key, deque())
        while bucket and now - bucket[0] > self.window_seconds:
            bucket.popleft()
        if not bucket:
            self._failures.pop(key, None)
            bucket = deque()
        return bucket

    def retry_after(self, *keys: str) -> int:
        """Seconds until another attempt is allowed (0 if allowed now)."""
        now = time.monotonic()
        wait = 0.0
        for key in keys:
            bucket = self._prune(key, now)
            if len(bucket) >= self.max_failures:
                wait = max(wait, self.window_seconds - (now - bucket[0]))
        return int(wait) + (1 if wait > 0 else 0)

    def record_failure(self, *keys: str) -> None:
        now = time.monotonic()
        for key in keys:
            self._prune(key, now)
            self._failures.setdefault(key, deque()).append(now)

    def reset(self, *keys: str) -> None:
        for key in keys:
            self._failures.pop(key, None)
