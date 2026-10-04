"""AnalysisService: live seeding, incremental updates, cadence, MTF context, cleanup."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
from datetime import timedelta
from typing import Any

import pytest

from app.analysis.service import INTERNAL_CONSUMER, LIVE_FIELDS, AnalysisService
from app.market_data.engine import MarketDataEngine
from app.market_data.models import Candle
from app.market_data.timeframes import Timeframe
from tests.analysis.helpers import load_fixture
from tests.market.fakes import FakeProvider, FakePublisher

M5 = Timeframe.M5


def _next(c: Candle, steps: int = 1, *, closed: bool = True) -> Candle:
    return replace(c, open_time=c.open_time + timedelta(minutes=5 * steps), is_closed=closed)


@dataclass
class Env:
    engine: MarketDataEngine
    service: AnalysisService
    provider: FakeProvider
    publisher: FakePublisher
    candles: list[Candle]


@pytest.fixture
async def env() -> AsyncIterator[Env]:
    provider = FakeProvider()
    publisher = FakePublisher()
    engine = MarketDataEngine(provider, publisher)
    await engine.symbols.refresh()
    engine.provider.set_stream_handlers(
        on_candle=engine._on_candle,
        on_quote=engine._on_quote,
        on_state=engine._on_state,
        on_reconnected=engine._on_reconnected,
    )
    candles, _ = load_fixture("okx_btcusdt_5m")
    provider.candles[("BTCUSDT", M5)] = candles
    service = AnalysisService(
        engine, lookback=1000, live_interval=0.05, live_min_interval=0.0, loop_interval=0.01
    )
    await service.start()
    yield Env(engine, service, provider, publisher, candles)
    await service.stop()


async def _wait(predicate: Any, timeout: float = 2.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not reached")
        await asyncio.sleep(0.01)


async def _subscribe(engine: MarketDataEngine, service: AnalysisService, consumer: str) -> None:
    await engine.subscribe(consumer, "BTCUSDT", M5)
    await service.subscribe(consumer, "BTCUSDT", M5)


def _updates(publisher: FakePublisher, consumer: str = "c1") -> list[dict[str, Any]]:
    return publisher.of_type("analysis.update", consumer)


async def test_subscribe_seeds_then_sends_full_snapshot(env: Env) -> None:
    engine = env.engine
    service = env.service
    publisher = env.publisher
    candles = env.candles
    await _subscribe(engine, service, "c1")
    first = _updates(publisher)[0]
    assert first["kind"] == "full" and first["analysis_ready"] is False
    assert first["reason"] == "loading_history"
    await _wait(lambda: any(u.get("analysis_ready") for u in _updates(publisher)))
    full = next(u for u in _updates(publisher) if u.get("analysis_ready"))
    assert full["symbol"] == "BTCUSDT" and full["timeframe"] == "5m"
    assert full["candle_time"] == candles[-1].open_ms // 1000
    assert full["candles_analyzed"] == len(candles)
    # Higher-timeframe context is subscribed internally (15m + 1h for 5m).
    assert INTERNAL_CONSUMER in engine.subscriptions.consumers_of(("BTCUSDT", Timeframe.M15))
    assert INTERNAL_CONSUMER in engine.subscriptions.consumers_of(("BTCUSDT", Timeframe.H1))
    assert [f["timeframe"] for f in full["multi_timeframe"]["higher"]] == ["15m", "1h"]


async def test_closed_candle_advances_incrementally(env: Env) -> None:
    engine = env.engine
    service = env.service
    provider = env.provider
    publisher = env.publisher
    candles = env.candles
    await _subscribe(engine, service, "c1")
    await _wait(lambda: service.snapshot(("BTCUSDT", M5)) is not None)
    analyzer = service._entries[("BTCUSDT", M5)].analyzer
    publisher.clear()
    nxt = _next(candles[-1])
    await provider.push(nxt)
    fulls = [u for u in _updates(publisher) if u["kind"] == "full"]
    assert fulls and fulls[-1]["candle_time"] == nxt.open_ms // 1000
    assert service._entries[("BTCUSDT", M5)].analyzer is analyzer  # same object: incremental
    assert service.stats["reseeds"] == 0


async def test_forming_updates_are_throttled_live_payloads(env: Env) -> None:
    engine = env.engine
    service = env.service
    provider = env.provider
    publisher = env.publisher
    candles = env.candles
    await _subscribe(engine, service, "c1")
    await _wait(lambda: service.snapshot(("BTCUSDT", M5)) is not None)
    publisher.clear()
    forming = _next(candles[-1], closed=False)
    await provider.push(forming)
    await _wait(lambda: any(u["kind"] == "live" for u in _updates(publisher)))
    live = next(u for u in _updates(publisher) if u["kind"] == "live")
    assert set(live) == {"kind", *LIVE_FIELDS}
    assert live["forming_time"] == forming.open_ms // 1000
    assert live["forming_candle"]["status"] == "developing"
    # No new forming data -> no further live updates.
    count = len(_updates(publisher))
    await asyncio.sleep(0.1)
    assert len(_updates(publisher)) == count


async def test_gap_or_resync_triggers_reseed(env: Env) -> None:
    engine = env.engine
    service = env.service
    candles = env.candles
    await _subscribe(engine, service, "c1")
    await _wait(lambda: service.snapshot(("BTCUSDT", M5)) is not None)
    service.on_candle(_next(candles[-1], 3))  # skips two candles
    assert service.stats["reseeds"] == 1
    await _wait(lambda: service._entries[("BTCUSDT", M5)].state == "ready")
    service.on_resync(("BTCUSDT", M5))
    assert service.stats["reseeds"] == 2
    await _wait(lambda: service._entries[("BTCUSDT", M5)].state == "ready")


async def test_corrected_closed_candle_triggers_reseed(env: Env) -> None:
    engine = env.engine
    service = env.service
    candles = env.candles
    await _subscribe(engine, service, "c1")
    await _wait(lambda: service.snapshot(("BTCUSDT", M5)) is not None)
    service.on_candle(candles[-1])  # identical duplicate: ignored
    assert service.stats["reseeds"] == 0
    service.on_candle(replace(candles[-1], close=candles[-1].close + 1))
    assert service.stats["reseeds"] == 1


async def test_release_all_cleans_up_context(env: Env) -> None:
    engine = env.engine
    service = env.service
    await _subscribe(engine, service, "c1")
    await _subscribe(engine, service, "c2")
    await _wait(lambda: service.snapshot(("BTCUSDT", M5)) is not None)
    await service.release_all("c1")
    assert ("BTCUSDT", M5) in service._entries  # c2 still watches
    await service.release_all("c2")
    await engine.release_all("c1")
    await engine.release_all("c2")
    assert service._entries == {}
    assert engine.subscriptions.app_keys == []


async def test_rest_latest_works_without_subscription(env: Env) -> None:
    service = env.service
    payload = await service.latest("BTCUSDT", M5)
    assert payload["analysis_ready"] is True and payload["kind"] == "full"
    history = await service.history("BTCUSDT", M5, 50)
    assert len(history["rows"]) == 50
    empty = await service.latest("BTCUSDT", Timeframe.M1)
    assert empty["analysis_ready"] is False and empty["reason"] == "insufficient_history"
