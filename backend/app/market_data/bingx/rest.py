"""Async BingX REST client: pooled httpx, token-bucket rate limiting, bounded retries.

Retry policy:
- network errors / timeouts / 5xx: up to REST_MAX_ATTEMPTS with exponential backoff + jitter
- 429 / 418 / throttling business codes: a shared cooldown (Retry-After or >= 5s) is set
  so *all* requests pause; never retried in a tight loop
- other 4xx and non-zero business codes: not retried
"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Callable, Mapping
from typing import Any

import httpx

from app.core.logging import get_logger
from app.market_data.bingx.constants import (
    RATE_LIMIT_CODES,
    RATE_LIMIT_MIN_COOLDOWN_SECONDS,
    REST_BURST,
    REST_MAX_ATTEMPTS,
    REST_MAX_CONCURRENCY,
    REST_RATE_PER_SECOND,
    REST_TIMEOUT_SECONDS,
)
from app.market_data.bingx.exceptions import (
    BingXApiError,
    BingXInvalidResponse,
    BingXRateLimited,
    BingXUnavailable,
)

logger = get_logger(__name__)

HealthHook = Callable[[bool, str | None], None]


class TokenBucket:
    """Async token bucket. `acquire()` waits (never spins) until a token is available."""

    def __init__(
        self, rate: float, burst: int, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._rate = rate
        self._capacity = float(burst)
        self._tokens = float(burst)
        self._clock = clock
        self._updated = clock()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = self._clock()
                self._tokens = min(
                    self._capacity, self._tokens + (now - self._updated) * self._rate
                )
                self._updated = now
                if self._tokens >= 1:
                    self._tokens -= 1
                    return
                await asyncio.sleep((1 - self._tokens) / self._rate)


class BingXRestClient:
    def __init__(
        self,
        base_url: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        rate_per_second: float = REST_RATE_PER_SECOND,
        burst: int = REST_BURST,
        max_concurrency: int = REST_MAX_CONCURRENCY,
        max_attempts: int = REST_MAX_ATTEMPTS,
        backoff_base: float = 0.5,
        sleep: Callable[[float], Any] = asyncio.sleep,
        on_result: HealthHook | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(REST_TIMEOUT_SECONDS),
            limits=httpx.Limits(
                max_connections=max_concurrency, max_keepalive_connections=max_concurrency
            ),
            headers={"Accept": "application/json", "User-Agent": "NeuralShot/0.2 (analysis-only)"},
            transport=transport,
        )
        self._bucket = TokenBucket(rate_per_second, burst)
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._max_attempts = max_attempts
        self._backoff_base = backoff_base
        self._sleep = sleep
        self._cooldown_until = 0.0
        self._on_result = on_result
        self.rate_limited_count = 0

    async def close(self) -> None:
        await self._client.aclose()

    async def get(self, path: str, params: Mapping[str, str | int] | None = None) -> Any:
        """GET a public endpoint and return the `data` field of the BingX envelope."""
        last_error: Exception | None = None
        for attempt in range(1, self._max_attempts + 1):
            await self._wait_cooldown()
            try:
                result = await self._request_once(path, params)
            except BingXRateLimited as exc:
                self._report(False, "rate_limited")
                raise exc
            except BingXUnavailable as exc:
                last_error = exc
                if attempt == self._max_attempts:
                    break
                delay = self._backoff_base * 2 ** (attempt - 1) * (1 + random.random() * 0.3)  # noqa: S311
                logger.info(
                    "bingx.rest_retry",
                    extra={"fields": {"path": path, "attempt": attempt, "delay": round(delay, 2)}},
                )
                await self._sleep(delay)
                continue
            self._report(True, None)
            return result
        self._report(False, str(last_error))
        raise BingXUnavailable(f"{path}: {last_error}")

    async def _request_once(self, path: str, params: Mapping[str, str | int] | None) -> Any:
        await self._bucket.acquire()
        async with self._semaphore:
            try:
                response = await self._client.get(path, params=params)
            except httpx.HTTPError as exc:
                raise BingXUnavailable(f"{type(exc).__name__}: {exc}") from exc

        if response.status_code in (429, 418):
            raise self._rate_limited(path, response.headers.get("Retry-After"))
        if response.status_code >= 500:
            raise BingXUnavailable(f"HTTP {response.status_code}")
        if response.status_code == 404:
            raise BingXApiError(404, "not found")
        if response.status_code >= 400:
            raise BingXApiError(response.status_code, response.text[:200])

        try:
            payload = response.json()
        except ValueError as exc:
            raise BingXInvalidResponse(f"{path}: body is not JSON") from exc
        if not isinstance(payload, Mapping) or "code" not in payload:
            raise BingXInvalidResponse(f"{path}: missing envelope")
        code = payload.get("code")
        if code in RATE_LIMIT_CODES:
            raise self._rate_limited(path, None)
        if code != 0:
            raise BingXApiError(
                int(code) if isinstance(code, int) else -1, str(payload.get("msg", ""))
            )
        return payload.get("data")

    def _rate_limited(self, path: str, retry_after_header: str | None) -> BingXRateLimited:
        try:
            retry_after = float(retry_after_header) if retry_after_header else 0.0
        except ValueError:
            retry_after = 0.0
        retry_after = max(retry_after, RATE_LIMIT_MIN_COOLDOWN_SECONDS)
        self._cooldown_until = max(self._cooldown_until, time.monotonic() + retry_after)
        self.rate_limited_count += 1
        logger.warning(
            "bingx.rate_limited",
            extra={
                "fields": {
                    "path": path,
                    "cooldown_s": retry_after,
                    "count": self.rate_limited_count,
                }
            },
        )
        return BingXRateLimited(retry_after)

    async def _wait_cooldown(self) -> None:
        remaining = self._cooldown_until - time.monotonic()
        if remaining > 0:
            await self._sleep(remaining)

    def _report(self, ok: bool, error: str | None) -> None:
        if self._on_result is not None:
            self._on_result(ok, error)
