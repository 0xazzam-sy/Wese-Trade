from __future__ import annotations

import time
from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.state import AppResources
from app.main import create_app
from app.market_data.engine import MarketDataEngine
from app.market_data.exceptions import ProviderRateLimited
from app.market_data.timeframes import Timeframe
from app.models.user import User
from tests.conftest import ADMIN_PASSWORD, ADMIN_USERNAME, FRONTEND_ORIGIN
from tests.market import fixtures as fx
from tests.market import helpers as h
from tests.market.fakes import FakeProvider

pytestmark = pytest.mark.usefixtures("admin_user")


def attach_engine(app: FastAPI) -> tuple[MarketDataEngine, FakeProvider]:
    resources: AppResources = app.state.resources
    provider = FakeProvider()
    engine = MarketDataEngine(provider, resources.connections)
    resources.market = engine
    return engine, provider


@pytest.fixture
async def market_client(
    app: FastAPI,
) -> AsyncIterator[tuple[httpx.AsyncClient, MarketDataEngine, FakeProvider]]:
    engine, provider = attach_engine(app)
    await engine.symbols.refresh()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/api/v1/auth/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD}
        )
        assert response.status_code == 200
        yield client, engine, provider


async def test_symbols_endpoint(
    market_client: tuple[httpx.AsyncClient, MarketDataEngine, FakeProvider],
) -> None:
    client, _, _ = market_client
    body = (await client.get("/api/v1/markets/symbols")).json()
    assert body["default_symbol"] == "BTCUSDT"
    assert [s["symbol"] for s in body["items"]] == ["BTCUSDT", "ETHUSDT"]  # active only
    btc = body["items"][0]
    assert btc["tick_size"] == "0.1"
    assert btc["price_precision"] == 1
    assert btc["status"] == "active"

    every = (await client.get("/api/v1/markets/symbols", params={"active_only": "false"})).json()
    assert every["total"] == 3
    search = (await client.get("/api/v1/markets/symbols", params={"search": "eth"})).json()
    assert [s["symbol"] for s in search["items"]] == ["ETHUSDT"]


async def test_candles_endpoint_validation_and_payload(
    market_client: tuple[httpx.AsyncClient, MarketDataEngine, FakeProvider],
) -> None:
    client, _, provider = market_client
    provider.candles[("BTCUSDT", Timeframe.M1)] = [h.candle(m, tf=Timeframe.M1) for m in (0, 1, 2)]
    ok = await client.get("/api/v1/markets/BTCUSDT/candles", params={"timeframe": "1m", "limit": 2})
    assert ok.status_code == 200
    body = ok.json()
    assert body["symbol"] == "BTCUSDT"
    assert body["timeframe"] == "1m"
    assert [c["time"] for c in body["candles"]] == [h.at(1) // 1000, h.at(2) // 1000]
    assert body["candles"][0]["open"] == "100"

    assert (
        await client.get("/api/v1/markets/BTCUSDT/candles", params={"timeframe": "2m"})
    ).status_code == 422
    assert (
        await client.get(
            "/api/v1/markets/BTCUSDT/candles", params={"timeframe": "1m", "limit": 5000}
        )
    ).status_code == 422
    unknown = await client.get("/api/v1/markets/NOPEUSDT/candles", params={"timeframe": "1m"})
    assert unknown.status_code == 404
    assert unknown.json() == {"detail": "unknown_symbol"}
    offline = await client.get("/api/v1/markets/OLDUSDT/candles", params={"timeframe": "1m"})
    assert offline.status_code == 409


async def test_exchange_outage_and_rate_limit_map_to_503(
    market_client: tuple[httpx.AsyncClient, MarketDataEngine, FakeProvider],
) -> None:
    client, _, provider = market_client
    provider.fail_rest = True
    down = await client.get("/api/v1/markets/BTCUSDT/candles", params={"timeframe": "5m"})
    assert down.status_code == 503
    assert down.json() == {"detail": "market_data_unavailable"}
    assert (await client.get("/api/v1/health")).status_code == 200  # app unaffected

    async def limited() -> list[object]:
        raise ProviderRateLimited(7)

    provider.fail_rest = False
    provider.fetch_tickers = limited  # type: ignore[method-assign,assignment]
    throttled = await client.get("/api/v1/markets/tickers")
    assert throttled.status_code == 503
    assert throttled.headers["retry-after"] == "8"


async def test_tickers_details_and_health(
    market_client: tuple[httpx.AsyncClient, MarketDataEngine, FakeProvider],
) -> None:
    client, _, provider = market_client
    from app.market_data.okx.parser import parse_funding, parse_mark_prices, parse_tickers
    from app.utils.time import utc_now

    async def tickers() -> list[object]:
        return parse_tickers(fx.TICKERS)  # type: ignore[return-value]

    async def funding() -> list[object]:
        return parse_funding(fx.FUNDING, now=utc_now())  # type: ignore[return-value]

    async def marks() -> object:
        return parse_mark_prices(fx.MARK_PRICES)

    provider.fetch_tickers = tickers  # type: ignore[method-assign,assignment]
    provider.fetch_funding = funding  # type: ignore[method-assign,assignment]
    provider.fetch_mark_prices = marks  # type: ignore[method-assign,assignment]
    items = (await client.get("/api/v1/markets/tickers")).json()["items"]
    btc = next(t for t in items if t["symbol"] == "BTCUSDT")
    assert btc["last_price"] == "84972.5"
    assert btc["volume_24h"] == "18775.1171"
    assert btc["quote_volume_24h"] is None

    details = (await client.get("/api/v1/markets/BTCUSDT/details")).json()
    assert details["symbol"]["symbol"] == "BTCUSDT"
    assert details["ticker"]["high_24h"] == "85044.6"
    assert details["funding"]["funding_rate"] == "0.0000289853709374"
    assert details["funding"]["mark_price"] == "84972.3"
    assert details["funding"]["next_funding_time"] == "2026-10-04T08:00:00Z"
    assert details["symbol"]["contract_value"] == "0.01"
    assert details["open_interest"] is None  # source failed -> omitted, not faked
    assert details["book"] is None

    health = (await client.get("/api/v1/markets/health")).json()
    assert health["provider"] == "okx"
    assert set(health["feeds"]) == {"candles", "quotes"}
    assert health["symbol_count"] == 2
    assert "active_streams" in health


@pytest.fixture
def live_client(app: FastAPI) -> Iterator[tuple[TestClient, MarketDataEngine, FakeProvider]]:
    engine, provider = attach_engine(app)
    with TestClient(app) as client:
        assert (
            client.post(
                "/api/v1/auth/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD}
            ).status_code
            == 200
        )
        deadline = time.monotonic() + 3
        while not engine.symbols.loaded and time.monotonic() < deadline:
            time.sleep(0.01)
        yield client, engine, provider


def _receive_until(ws: object, event_type: str, limit: int = 20) -> dict[str, object]:
    for _ in range(limit):
        message = ws.receive_json()  # type: ignore[attr-defined]
        if message["type"] == event_type:
            return message  # type: ignore[no-any-return]
    raise AssertionError(f"{event_type} not received")


def test_ws_market_subscription_flow(
    live_client: tuple[TestClient, MarketDataEngine, FakeProvider],
) -> None:
    client, engine, provider = live_client
    with client.websocket_connect("/api/v1/ws", headers={"origin": FRONTEND_ORIGIN}) as ws:
        assert ws.receive_json()["type"] == "system.status"
        status = _receive_until(ws, "market.status")
        assert status["data"]["provider"] == "okx"  # type: ignore[index]

        ws.send_json({"type": "market.subscribe", "data": {"symbol": "btcusdt", "timeframe": "1m"}})
        ack = _receive_until(ws, "market.subscribed")
        assert ack["data"] == {"symbol": "BTCUSDT", "timeframe": "1m"}
        assert provider.subscribed == [("BTCUSDT", Timeframe.M1)]

        client.portal.call(provider.push, h.candle(0, tf=Timeframe.M1, c="123.4", closed=False))  # type: ignore[union-attr]
        event = _receive_until(ws, "market.candle")
        assert event["data"]["candle"]["close"] == "123.4"  # type: ignore[index]
        tick = _receive_until(ws, "market.tick")
        assert tick["data"]["price"] == "123.4"  # type: ignore[index]

        ws.send_json({"type": "market.subscribe", "data": {"symbol": "NOPE", "timeframe": "1m"}})
        assert _receive_until(ws, "system.error")["data"]["code"] == "unknown_symbol"  # type: ignore[index]
        ws.send_json({"type": "market.subscribe", "data": {"symbol": "BTCUSDT", "timeframe": "7m"}})
        assert _receive_until(ws, "system.error")["data"]["code"] == "invalid_timeframe"  # type: ignore[index]

    # Disconnect releases the exchange subscription.
    deadline = time.monotonic() + 2
    while provider.subscribed and time.monotonic() < deadline:
        time.sleep(0.01)
    assert provider.subscribed == []
    del engine


def test_ws_market_disabled_reports_error(
    app: FastAPI, admin_user: User, settings: Settings
) -> None:
    with TestClient(app) as client:
        client.post(
            "/api/v1/auth/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD}
        )
        with client.websocket_connect("/api/v1/ws", headers={"origin": FRONTEND_ORIGIN}) as ws:
            ws.receive_json()
            ws.send_json(
                {"type": "market.subscribe", "data": {"symbol": "BTCUSDT", "timeframe": "1m"}}
            )
            assert _receive_until(ws, "system.error")["data"]["code"] == "market_data_disabled"  # type: ignore[index]
    del settings


def test_engine_built_from_settings_when_enabled(settings: Settings) -> None:
    app = create_app(settings.model_copy(update={"market_data_enabled": True}))
    resources: AppResources = app.state.resources
    assert resources.market is not None
    assert resources.market.provider.name == "okx"
