"""Persistence, REST endpoints, live SignalService events."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.service import AnalysisService
from app.core.state import AppResources
from app.market_data.engine import MarketDataEngine
from app.market_data.timeframes import Timeframe
from app.services import signal_store
from app.signal_engine.enums import SignalState
from app.signal_engine.lifecycle import SignalTracker
from app.signal_engine.models import Signal
from app.signal_engine.service import SignalService
from tests.analysis.helpers import load_fixture
from tests.conftest import ADMIN_PASSWORD, ADMIN_USERNAME
from tests.market.fakes import FakeProvider, FakePublisher
from tests.signals.test_lifecycle import bar, base_eval, tracker, with_plan

pytestmark = pytest.mark.usefixtures("admin_user")

FORBIDDEN = ("probability", "احتمال", "win_chance", "leverage", "order")


def _walk_keys(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [*value.keys(), *(k for v in value.values() for k in _walk_keys(v))]
    if isinstance(value, list):
        return [k for v in value for k in _walk_keys(v)]
    return []


def _confirmed_signal() -> tuple[SignalTracker, Signal]:
    tr, _ = tracker()
    s = tr.on_evaluation(with_plan(base_eval()), bar(0, 99, 100.5, 98.9, 100))
    assert s is not None
    return tr, s


async def test_persistence_freezes_original_fields(session: AsyncSession) -> None:
    tr, s = _confirmed_signal()
    await signal_store.upsert_signal(session, s, "live")
    tr.on_bar(bar(1, 99.5, 99.8, 97.5, 97.8))  # stopped
    s.score = 1.0  # even if an in-memory field were mutated, the stored original stays
    await signal_store.upsert_signal(session, s, "live")
    rows = await signal_store.list_signals(session, "BTCUSDT", "5m", 10)
    assert len(rows) == 1
    row = rows[0]
    assert row["state"] == SignalState.STOPPED.value
    assert row["score"] != 1.0
    assert row["outcome"]["net_r"] is not None and row["outcome"]["exit_reason"] == "stop"
    assert row["positive"] and row["components"] and row["evidence"]["trigger"]["id"]
    assert row["plan"]["rr"] == list(s.plan.rr())
    assert await signal_store.recent_signal_ids(session, "BTCUSDT", "5m") == {s.id}


def _attach(app: FastAPI) -> tuple[MarketDataEngine, SignalService]:
    resources: AppResources = app.state.resources
    provider = FakeProvider()
    candles, _ = load_fixture("okx_btcusdt_5m")
    provider.candles[("BTCUSDT", Timeframe.M5)] = candles
    engine = MarketDataEngine(provider, resources.connections)
    analysis = AnalysisService(engine)
    signals = SignalService(analysis, engine, resources.database)
    resources.market, resources.analysis, resources.signals = engine, analysis, signals
    return engine, signals


@pytest.fixture
async def api(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    engine, _ = _attach(app)
    await engine.symbols.refresh()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        login = {"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD}
        assert (await client.post("/api/v1/auth/login", json=login)).status_code == 200
        yield client


async def test_signal_endpoint_returns_transparent_evaluation(api: httpx.AsyncClient) -> None:
    response = await api.get("/api/v1/signals/btcusdt", params={"timeframe": "5m"})
    assert response.status_code == 200
    body = response.json()
    ev = body["evaluation"]
    assert ev["signal_class"] in {"STRONG_BUY", "BUY", "NEUTRAL", "SELL", "STRONG_SELL"}
    assert ev["strategy_version"].startswith("wese-trade-signal-")
    if ev["signal_class"] == "NEUTRAL":
        assert ev["neutral_reason"]
    assert set(body) == {
        "symbol",
        "timeframe",
        "evaluation",
        "developing",
        "active",
        "last_confirmed",
    }
    for key in _walk_keys(body):
        assert not any(word in key.lower() for word in FORBIDDEN), key
    assert (await api.get("/api/v1/signals/NOPE", params={"timeframe": "5m"})).status_code == 404


async def test_history_and_backtest_endpoints(
    api: httpx.AsyncClient, session: AsyncSession
) -> None:
    _, s = _confirmed_signal()
    await signal_store.upsert_signal(session, s, "live")
    hist = (await api.get("/api/v1/signals/BTCUSDT/history", params={"timeframe": "5m"})).json()
    assert [i["id"] for i in hist["items"]] == [s.id]
    assert (
        await api.get("/api/v1/signals/BTCUSDT/history", params={"limit": 101})
    ).status_code == 422
    report = {
        "strategy_version": "v1",
        "config": {"regular_threshold": 75.0},
        "data": [],
        "all": {"overall": {"entered": 1}},
        "dev": {"overall": {}},
        "holdout": {"overall": {"entered": 0}},
    }
    run_id = await signal_store.save_backtest_run(session, "t", report)
    runs = (await api.get("/api/v1/backtests")).json()["items"]
    assert runs[0]["id"] == run_id and runs[0]["strategy_version"] == "v1"
    detail = (await api.get(f"/api/v1/backtests/{run_id}")).json()
    assert detail["summary"]["holdout"]["overall"]["entered"] == 0
    assert (await api.get("/api/v1/backtests/999")).status_code == 404


async def test_live_service_publishes_evaluation_after_context_and_never_on_stale() -> None:
    provider = FakeProvider()
    candles, _ = load_fixture("okx_btcusdt_5m")
    provider.candles[("BTCUSDT", Timeframe.M5)] = candles
    publisher = FakePublisher()
    engine = MarketDataEngine(provider, publisher)
    await engine.symbols.refresh()
    analysis = AnalysisService(engine, loop_interval=0.01)
    signals = SignalService(analysis, engine, None)
    await engine.subscribe("c1", "BTCUSDT", Timeframe.M5)
    await analysis.subscribe("c1", "BTCUSDT", Timeframe.M5)
    for _ in range(200):
        if analysis.analyzer(("BTCUSDT", Timeframe.M5)) is not None:
            break
        await asyncio.sleep(0.01)
    key = ("BTCUSDT", Timeframe.M5)
    analyzer = analysis.analyzer(key)
    assert analyzer is not None
    signals.on_closed(key, analyzer)
    updates = publisher.of_type("signal.updated", "c1")
    assert updates and updates[-1]["evaluation"]["symbol"] == "BTCUSDT"
    # The stream is not "live" in this offline setup -> every evaluation is NEUTRAL (stale gate).
    assert updates[-1]["evaluation"]["signal_class"] == "NEUTRAL"
    signals.subscribe("c2", key)  # a late subscriber gets the current state (nothing for c2 yet)
    state = signals.state(key)
    assert state["evaluation"] is not None and state["active"] is None
    await analysis.stop()


async def test_seed_evaluation_is_display_only_and_withholds_trades(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = FakeProvider()
    candles, _ = load_fixture("okx_btcusdt_5m")
    provider.candles[("BTCUSDT", Timeframe.M5)] = candles
    publisher = FakePublisher()
    engine = MarketDataEngine(provider, publisher)
    await engine.symbols.refresh()
    analysis = AnalysisService(engine, loop_interval=0.01)
    signals = SignalService(analysis, engine, None)
    await engine.subscribe("c1", "BTCUSDT", Timeframe.M5)
    await analysis.subscribe("c1", "BTCUSDT", Timeframe.M5)
    key = ("BTCUSDT", Timeframe.M5)
    for _ in range(200):
        if analysis.analyzer(key) is not None:
            break
        await asyncio.sleep(0.01)
    analyzer = analysis.analyzer(key)
    assert analyzer is not None
    stream = signals.streams[key]
    # Context timeframes (15m/1h) are not seeded here, so the seed evaluation waits.
    assert stream.seed_pending and stream.current is None
    signals._try_seed(stream, force=True)  # what the loop does after CONTEXT_WAIT_SECONDS
    seeded = [u for u in publisher.of_type("signal.updated", "c1") if "evaluation" in u]
    assert seeded and seeded[-1]["evaluation"]["signal_class"] == "NEUTRAL"
    assert stream.tracker.active is None and signals.stats["evaluations"] == 0

    # A non-NEUTRAL seed result is never shown or tracked: no live signal was issued for it.
    stream.current, stream.seed_pending = None, True
    trade = SimpleNamespace(is_trade=True)
    monkeypatch.setattr("app.signal_engine.service.evaluate_closed", lambda *a, **k: trade)
    before = len(publisher.of_type("signal.updated", "c1"))
    signals._try_seed(stream, force=True)
    assert stream.current is None and stream.tracker.active is None
    assert len(publisher.of_type("signal.updated", "c1")) == before
    await analysis.stop()
