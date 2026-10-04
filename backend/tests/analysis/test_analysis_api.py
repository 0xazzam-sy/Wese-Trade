"""REST + WebSocket surface of the analysis engine."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.analysis.service import AnalysisService
from app.core.state import AppResources
from app.market_data.engine import MarketDataEngine
from app.market_data.timeframes import Timeframe
from tests.analysis.helpers import load_fixture
from tests.conftest import ADMIN_PASSWORD, ADMIN_USERNAME, FRONTEND_ORIGIN
from tests.market.fakes import FakeProvider

pytestmark = pytest.mark.usefixtures("admin_user")


def attach(app: FastAPI) -> tuple[MarketDataEngine, FakeProvider, AnalysisService]:
    resources: AppResources = app.state.resources
    provider = FakeProvider()
    candles, _ = load_fixture("okx_btcusdt_5m")
    provider.candles[("BTCUSDT", Timeframe.M5)] = candles
    engine = MarketDataEngine(provider, resources.connections)
    service = AnalysisService(engine, include_debug=True)
    resources.market, resources.analysis = engine, service
    return engine, provider, service


@pytest.fixture
async def api(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    engine, _, _ = attach(app)
    await engine.symbols.refresh()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        login = {"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD}
        assert (await client.post("/api/v1/auth/login", json=login)).status_code == 200
        yield client


async def test_analysis_endpoint_returns_snapshot(api: httpx.AsyncClient) -> None:
    response = await api.get("/api/v1/analysis/btcusdt", params={"timeframe": "5m"})
    assert response.status_code == 200
    body = response.json()
    assert body["symbol"] == "BTCUSDT" and body["timeframe"] == "5m"
    assert body["analysis_ready"] is True
    assert body["swing_structure"]["layer"] == "swing"
    assert body["debug"] is not None  # non-production


async def test_analysis_not_ready_and_errors(api: httpx.AsyncClient) -> None:
    short = (await api.get("/api/v1/analysis/BTCUSDT", params={"timeframe": "1m"})).json()
    assert short["analysis_ready"] is False and short["reason"] == "insufficient_history"
    missing = await api.get("/api/v1/analysis/NOPE", params={"timeframe": "5m"})
    assert missing.status_code == 404
    bad = await api.get("/api/v1/analysis/BTCUSDT", params={"timeframe": "7m"})
    assert bad.status_code == 422


async def test_history_is_limited(api: httpx.AsyncClient) -> None:
    ok = await api.get("/api/v1/analysis/BTCUSDT/history", params={"timeframe": "5m", "limit": 20})
    body = ok.json()
    assert ok.status_code == 200 and len(body["rows"]) == 20
    assert {"time", "trend", "regime", "rsi", "swing_structure"} <= set(body["rows"][0])
    too_many = await api.get(
        "/api/v1/analysis/BTCUSDT/history", params={"timeframe": "5m", "limit": 301}
    )
    assert too_many.status_code == 422


async def test_analysis_requires_auth(app: FastAPI) -> None:
    attach(app)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/api/v1/analysis/BTCUSDT", params={"timeframe": "5m"})
        assert response.status_code == 401


@pytest.fixture
def ws_client(app: FastAPI) -> Iterator[tuple[TestClient, MarketDataEngine]]:
    engine, _, _ = attach(app)
    with TestClient(app) as client:
        login = {"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD}
        assert client.post("/api/v1/auth/login", json=login).status_code == 200
        deadline = time.monotonic() + 3
        while not engine.symbols.loaded and time.monotonic() < deadline:
            time.sleep(0.01)
        yield client, engine


def test_ws_subscription_streams_analysis(ws_client: tuple[TestClient, MarketDataEngine]) -> None:
    client, engine = ws_client
    with client.websocket_connect("/api/v1/ws", headers={"origin": FRONTEND_ORIGIN}) as ws:
        ws.send_json({"type": "market.subscribe", "data": {"symbol": "BTCUSDT", "timeframe": "5m"}})
        ready = None
        for _ in range(50):
            message = ws.receive_json()
            if message["type"] == "analysis.update" and message["data"].get("analysis_ready"):
                ready = message["data"]
                break
        assert ready is not None
        assert ready["kind"] == "full" and ready["symbol"] == "BTCUSDT"
        assert ready["timeframe"] == "5m"
    deadline = time.monotonic() + 2
    while engine.subscriptions.app_keys and time.monotonic() < deadline:
        time.sleep(0.01)
    assert engine.subscriptions.app_keys == []  # browser + internal context released
