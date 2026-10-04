from __future__ import annotations

from datetime import UTC, datetime
from itertools import pairwise
from typing import Any

import httpx
import pytest

from app.market_data.exceptions import (
    InvalidProviderResponse,
    ProviderApiError,
    ProviderRateLimited,
    ProviderUnavailable,
    UnknownSymbol,
)
from app.market_data.okx.parser import parse_instruments
from app.market_data.okx.provider import OkxProvider
from app.market_data.okx.rest import OkxRestClient, TokenBucket
from app.market_data.okx.stream import OkxSocket
from app.market_data.timeframes import Timeframe
from tests.market import fixtures as fx

BASE = "https://openapi.okx.com"


def client_for(handler: Any, **kwargs: Any) -> tuple[OkxRestClient, list[float]]:
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    client = OkxRestClient(
        BASE,
        transport=httpx.MockTransport(handler),
        sleep=fake_sleep,
        rate_per_second=1000,
        burst=1000,
        **kwargs,
    )
    return client, sleeps


async def test_success_returns_data_and_sends_no_credentials() -> None:
    results: list[bool] = []
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=fx.envelope(fx.INSTRUMENTS))

    client, _ = client_for(handler, on_result=lambda ok, _err: results.append(ok))
    data = await client.get("/api/v5/public/instruments", {"instType": "SWAP"})
    assert len(data) == len(fx.INSTRUMENTS)
    assert results == [True]
    headers = {k.lower() for k in seen[0].headers}
    assert not headers & {"ok-access-key", "ok-access-sign", "ok-access-passphrase"}
    await client.close()


async def test_transient_failures_are_retried_with_backoff() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("boom")
        if calls["n"] == 2:
            return httpx.Response(502)
        return httpx.Response(200, json=fx.envelope([]))

    client, sleeps = client_for(handler)
    assert await client.get("/x") == []
    assert calls["n"] == 3
    assert len(sleeps) == 2
    assert sleeps[1] > sleeps[0]
    await client.close()


async def test_gives_up_after_max_attempts() -> None:
    client, sleeps = client_for(lambda req: httpx.Response(503))
    with pytest.raises(ProviderUnavailable):
        await client.get("/x")
    assert len(sleeps) == 2
    await client.close()


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(429, headers={"Retry-After": "7"}, json=fx.envelope([], code="50011")),
        httpx.Response(200, json=fx.envelope([], code="50011", msg="Too Many Requests")),
    ],
)
async def test_rate_limit_sets_shared_cooldown_without_tight_retry(
    response: httpx.Response,
) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return response

    client, sleeps = client_for(handler)
    with pytest.raises(ProviderRateLimited) as exc:
        await client.get("/x")
    assert exc.value.retry_after >= 5
    assert calls["n"] == 1
    assert client.rate_limited_count == 1
    with pytest.raises(ProviderRateLimited):
        await client.get("/x")
    assert sleeps
    assert sleeps[0] > 4  # waited for the cooldown before the next request
    await client.close()


@pytest.mark.parametrize(
    ("response", "error"),
    [
        (httpx.Response(200, text="not json"), InvalidProviderResponse),
        (httpx.Response(200, json={"data": []}), InvalidProviderResponse),
        (
            httpx.Response(200, json=fx.envelope([], code="51000", msg="Parameter bar error")),
            ProviderApiError,
        ),
        (
            httpx.Response(200, json=fx.envelope([], code="51001", msg="doesn't exist")),
            UnknownSymbol,
        ),
        (httpx.Response(404, text="not found"), ProviderApiError),
    ],
)
async def test_non_retryable_errors(response: httpx.Response, error: type[Exception]) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return response

    client, _ = client_for(handler)
    with pytest.raises(error):
        await client.get("/x", {"instId": "NOPE-USDT-SWAP"})
    assert calls["n"] == 1
    await client.close()


async def test_token_bucket_waits_instead_of_spinning() -> None:
    clock = {"t": 0.0}
    bucket = TokenBucket(rate=2, burst=1, clock=lambda: clock["t"])
    await bucket.acquire()
    clock["t"] = 0.5
    await bucket.acquire()


async def test_candle_pagination_recent_then_history() -> None:
    """/market/candles pages back 1440 rows; older pages continue on /history-candles."""
    step = Timeframe.M5.milliseconds
    newest = 1_791_095_100_000
    seen: list[tuple[str, int | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        after = request.url.params.get("after")
        top = int(after) - step if after else newest
        seen.append((request.url.path, int(after) if after else None))
        if request.url.path.endswith("/market/candles") and newest - top >= 1440 * step:
            return httpx.Response(200, json=fx.envelope([]))
        rows = [
            [
                str(top - i * step),
                "1",
                "2",
                "0.5",
                "1.5",
                "10",
                "1",
                "1.5",
                "0" if top - i * step == newest else "1",
            ]
            for i in range(int(request.url.params["limit"]))
        ]
        return httpx.Response(200, json=fx.envelope(rows))

    client, _ = client_for(handler)
    provider = OkxProvider(client, OkxSocket("public", "wss://x"), OkxSocket("business", "wss://x"))
    btc = parse_instruments(fx.INSTRUMENTS)[0]
    candles = await provider.fetch_candles(btc, Timeframe.M5, limit=1602)
    assert len(candles) == 1602
    opens = [c.open_ms for c in candles]
    assert all(b - a == step for a, b in pairwise(opens))
    assert candles[-1].open_ms == newest
    assert candles[-1].is_closed is False
    assert all(c.is_closed for c in candles[:-1])
    paths = [p for p, _ in seen]
    assert paths.count("/api/v5/market/candles") == 6  # 5 pages + 1 empty at the 1440 boundary
    assert paths[-1] == "/api/v5/market/history-candles"
    assert all(a is None or a > 0 for _, a in seen)
    await client.close()


async def test_candles_before_end_time_uses_after_exclusive() -> None:
    seen: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.params.get("after"))
        return httpx.Response(200, json=fx.envelope([]))

    client, _ = client_for(handler)
    provider = OkxProvider(client, OkxSocket("public", "wss://x"), OkxSocket("business", "wss://x"))
    btc = parse_instruments(fx.INSTRUMENTS)[0]
    end = datetime.fromtimestamp(1_791_090_000, tz=UTC)
    assert await provider.fetch_candles(btc, Timeframe.H1, limit=10, end_time=end) == []
    assert seen[0] == "1791090000001"  # records strictly older than end+1ms => open <= end
    await client.close()
