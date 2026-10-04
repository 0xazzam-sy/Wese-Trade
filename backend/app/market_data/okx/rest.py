"""Async OKX public REST client: pooled httpx, token-bucket rate limiting, bounded retries.

- network errors / timeouts / 5xx: up to REST_MAX_ATTEMPTS, exponential backoff + jitter
- HTTP 429 or OKX "Too Many Requests" codes: shared cooldown for ALL requests
  (Retry-After or >= 5s), raised as ProviderRateLimited; never retried in a tight loop
- other errors and non-zero OKX codes: not retried
No authentication headers are ever sent: public endpoints only.
"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Callable, Mapping
from typing import Any

import httpx

from app.core.logging import get_logger
from app.market_data.exceptions import (
    InvalidProviderResponse,
    ProviderApiError,
    ProviderRateLimited,
    ProviderUnavailable,
    UnknownSymbol,
)
from app.market_data.okx.constants import (
    RATE_LIMIT_CODES,
    RATE_LIMIT_MIN_COOLDOWN_SECONDS,
    REST_BURST,
    REST_MAX_ATTEMPTS,
    REST_MAX_CONCURRENCY,
    REST_RATE_PER_SECOND,
    REST_TIMEOUT_SECONDS,
    UNKNOWN_INSTRUMENT_CODES,
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


class OkxRestClient:
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
            headers={"Accept": "application/json", "User-Agent": "WeseTrade/0.3 (analysis-only)"},
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
        """GET a public endpoint and return the `data` field of the OKX envelope."""
        last_error: Exception | None = None
        for attempt in range(1, self._max_attempts + 1):
            await self._wait_cooldown()
            try:
                result = await self._request_once(path, params)
            except ProviderRateLimited:
                self._report(False, "rate_limited")
                raise
            except ProviderUnavailable as exc:
                last_error = exc
                if attempt == self._max_attempts:
                    break
                delay = self._backoff_base * 2 ** (attempt - 1) * (1 + random.random() * 0.3)  # noqa: S311
                logger.info(
                    "okx.rest_retry",
                    extra={"fields": {"path": path, "attempt": attempt, "delay": round(delay, 2)}},
                )
                await self._sleep(delay)
                continue
            self._report(True, None)
            return result
        self._report(False, str(last_error))
        raise ProviderUnavailable(f"{path}: {last_error}")

    async def _request_once(self, path: str, params: Mapping[str, str | int] | None) -> Any:
        await self._bucket.acquire()
        async with self._semaphore:
            try:
                response = await self._client.get(path, params=params)
            except httpx.HTTPError as exc:
                raise ProviderUnavailable(f"{type(exc).__name__}: {exc}") from exc

        if response.status_code == 429:
            raise self._rate_limited(path, response.headers.get("Retry-After"))
        if response.status_code >= 500:
            raise ProviderUnavailable(f"HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            if response.status_code >= 400:
                raise ProviderApiError(response.status_code, response.text[:200]) from exc
            raise InvalidProviderResponse(f"{path}: body is not JSON") from exc
        if not isinstance(payload, Mapping) or "code" not in payload:
            raise InvalidProviderResponse(f"{path}: missing envelope")
        code = str(payload.get("code"))
        if code in RATE_LIMIT_CODES:
            raise self._rate_limited(path, None)
        if code in UNKNOWN_INSTRUMENT_CODES:
            raise UnknownSymbol(str((params or {}).get("instId", "")))
        if code != "0":
            raise ProviderApiError(int(code) if code.isdigit() else -1, str(payload.get("msg", "")))
        if response.status_code >= 400:
            raise ProviderApiError(response.status_code, response.text[:200])
        return payload.get("data")

    def _rate_limited(self, path: str, retry_after_header: str | None) -> ProviderRateLimited:
        try:
            retry_after = float(retry_after_header) if retry_after_header else 0.0
        except ValueError:
            retry_after = 0.0
        retry_after = max(retry_after, RATE_LIMIT_MIN_COOLDOWN_SECONDS)
        self._cooldown_until = max(self._cooldown_until, time.monotonic() + retry_after)
        self.rate_limited_count += 1
        logger.warning(
            "okx.rate_limited",
            extra={
                "fields": {
                    "path": path,
                    "cooldown_s": retry_after,
                    "count": self.rate_limited_count,
                }
            },
        )
        return ProviderRateLimited(retry_after)

    async def _wait_cooldown(self) -> None:
        remaining = self._cooldown_until - time.monotonic()
        if remaining > 0:
            await self._sleep(remaining)

    def _report(self, ok: bool, error: str | None) -> None:
        if self._on_result is not None:
            self._on_result(ok, error)
