from __future__ import annotations

import itertools
from datetime import UTC, datetime

import httpx
import pytest

from app.market_data.bingx.exceptions import (
    BingXApiError,
    BingXInvalidResponse,
    BingXRateLimited,
    BingXUnavailable,
)
from app.market_data.bingx.parser import parse_contracts
from app.market_data.bingx.provider import BingXProvider
from app.market_data.bingx.rest import BingXRestClient, TokenBucket
from app.market_data.bingx.stream import BingXMarketStream
from app.market_data.timeframes import Timeframe
from tests.market import fixtures as fx

BASE = "https://open-api.bingx.com"


def client_for(handler: object, **kwargs: object) -> tuple[BingXRestClient, list[float]]:
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    client = BingXRestClient(
        BASE,
        transport=httpx.MockTransport(handler),  # type: ignore[arg-type]
        sleep=fake_sleep,
        rate_per_second=1000,
        burst=1000,
        **kwargs,  # type: ignore[arg-type]
    )
    return client, sleeps


async def test_success_returns_data_and_reports_health() -> None:
    results: list[bool] = []
    client, _ = client_for(
        lambda req: httpx.Response(200, json=fx.envelope(fx.CONTRACTS)),
        on_result=lambda ok, _err: results.append(ok),
    )
    data = await client.get("/openApi/swap/v2/quote/contracts")
    assert len(data) == len(fx.CONTRACTS)
    assert results == [True]
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
    assert len(sleeps) == 2 and sleeps[1] > sleeps[0]  # exponential
    await client.close()


async def test_gives_up_after_max_attempts() -> None:
    client, sleeps = client_for(lambda req: httpx.Response(503))
    with pytest.raises(BingXUnavailable):
        await client.get("/x")
    assert len(sleeps) == 2  # 3 attempts, no infinite loop
    await client.close()


async def test_rate_limit_sets_cooldown_and_is_not_retried_immediately() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429, headers={"Retry-After": "7"})

    client, sleeps = client_for(handler)
    with pytest.raises(BingXRateLimited) as exc:
        await client.get("/x")
    assert exc.value.retry_after == 7
    assert calls["n"] == 1
    assert client.rate_limited_count == 1
    # The next request waits for the shared cooldown before touching the network.
    with pytest.raises(BingXRateLimited):
        await client.get("/x")
    assert sleeps and sleeps[0] > 6
    await client.close()


async def test_rate_limit_business_code_and_minimum_cooldown() -> None:
    client, _ = client_for(lambda req: httpx.Response(200, json=fx.envelope(None, code=100410)))
    with pytest.raises(BingXRateLimited) as exc:
        await client.get("/x")
    assert exc.value.retry_after >= 5
    await client.close()


@pytest.mark.parametrize(
    ("response", "error"),
    [
        (httpx.Response(200, text="not json"), BingXInvalidResponse),
        (httpx.Response(200, json={"data": []}), BingXInvalidResponse),
        (httpx.Response(200, json=fx.envelope(None, code=80014, msg="bad")), BingXApiError),
        (httpx.Response(400, text="bad request"), BingXApiError),
    ],
)
async def test_non_retryable_errors(response: httpx.Response, error: type[Exception]) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return response

    client, _ = client_for(handler)
    with pytest.raises(error):
        await client.get("/x")
    assert calls["n"] == 1
    await client.close()


async def test_token_bucket_waits_instead_of_spinning() -> None:
    clock = {"t": 0.0}
    bucket = TokenBucket(rate=2, burst=1, clock=lambda: clock["t"])
    await bucket.acquire()
    clock["t"] = 0.5  # one token regenerated
    await bucket.acquire()


async def test_provider_paginates_klines_and_falls_back_to_v2() -> None:
    seen: list[httpx.URL] = []
    step_ms = Timeframe.M5.milliseconds
    end_open = 1_700_000_100_000 - (1_700_000_100_000 % step_ms)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url)
        if request.url.path.endswith("/v3/quote/klines"):
            return httpx.Response(404)
        limit = int(request.url.params["limit"])
        end = int(request.url.params.get("endTime", end_open))
        last = end - (end % step_ms)
        rows = [
            {
                "open": "1",
                "high": "2",
                "low": "0.5",
                "close": "1.5",
                "volume": "1",
                "time": last - i * step_ms,
            }
            for i in range(limit)
        ]
        return httpx.Response(200, json=fx.envelope(rows))

    client, _ = client_for(handler)
    provider = BingXProvider(client, BingXMarketStream("wss://example"))
    btc = parse_contracts(fx.CONTRACTS)[0]
    candles = await provider.fetch_candles(
        btc, Timeframe.M5, limit=2000, end_time=datetime.fromtimestamp(end_open / 1000, tz=UTC)
    )
    assert len(candles) == 2000
    opens = [c.open_ms for c in candles]
    assert opens == sorted(set(opens))
    assert all(b - a == step_ms for a, b in itertools.pairwise(opens))
    paths = [u.path for u in seen]
    assert paths[0].endswith("/v3/quote/klines")
    assert all(p.endswith("/v2/quote/klines") for p in paths[1:])
    assert len(paths) == 3  # 1 failed v3 + 2 pages (1440 + 560)
    await client.close()
