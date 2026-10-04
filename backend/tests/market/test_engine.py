from __future__ import annotations

import time
from collections.abc import AsyncIterator

import pytest

from app.market_data.bingx.exceptions import BingXUnavailable, SymbolUnavailable, UnknownSymbol
from app.market_data.engine import MarketDataEngine
from app.market_data.models import SymbolStatus
from app.market_data.timeframes import Timeframe
from tests.market import helpers as h
from tests.market.fakes import FakeProvider, FakePublisher


@pytest.fixture
async def setup(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[tuple[MarketDataEngine, FakeProvider, FakePublisher]]:
    # Freeze "now" at 12:07 so buckets are deterministic.
    monkeypatch.setattr("app.market_data.engine.now_ms", lambda: h.at(7))
    monkeypatch.setattr("app.market_data.services.candle_service.now_ms", lambda: h.at(7))
    provider, publisher = FakeProvider(), FakePublisher()
    engine = MarketDataEngine(provider, publisher, stale_after=0.05)
    provider.set_stream_handlers(
        on_candle=engine._on_candle,
        on_state=engine._on_state,
        on_reconnected=engine._on_reconnected,
    )
    engine.symbols.on_unavailable = engine._on_symbols_unavailable  # normally wired by start()
    await engine.symbols.refresh()
    await provider.set_state("connected")
    yield engine, provider, publisher
    await engine.stop()


async def test_unknown_and_unavailable_symbols_rejected(
    setup: tuple[MarketDataEngine, FakeProvider, FakePublisher],
) -> None:
    engine, _, _ = setup
    with pytest.raises(UnknownSymbol):
        await engine.subscribe("c1", "NOPEUSDT", Timeframe.M1)
    with pytest.raises(SymbolUnavailable):
        await engine.subscribe("c1", "OLDUSDT", Timeframe.M1)


async def test_default_symbol_and_search(
    setup: tuple[MarketDataEngine, FakeProvider, FakePublisher],
) -> None:
    engine, provider, _ = setup
    assert engine.symbols.default_symbol() == "BTCUSDT"
    assert [s.symbol for s in engine.symbols.list(search="eth")] == ["ETHUSDT"]
    provider.symbols = [s for s in provider.symbols if s.symbol != "BTCUSDT"]
    await engine.symbols.refresh()
    assert engine.symbols.default_symbol() == "ETHUSDT"  # safe fallback, no crash
    assert engine.symbols.get("BTCUSDT").status is SymbolStatus.DELISTED


async def test_subscriptions_are_shared_and_reference_counted(
    setup: tuple[MarketDataEngine, FakeProvider, FakePublisher],
) -> None:
    engine, provider, _ = setup
    await engine.subscribe("c1", "BTCUSDT", Timeframe.M5)
    await engine.subscribe("c2", "btc-usdt", Timeframe.M10)  # 10m reuses the 5m stream
    await engine.subscribe("c2", "BTCUSDT", Timeframe.M10)  # idempotent
    assert provider.subscribed == [("BTCUSDT", Timeframe.M5)]

    await engine.unsubscribe("c1", "BTCUSDT", Timeframe.M5)
    assert provider.subscribed == [("BTCUSDT", Timeframe.M5)]  # c2 still needs it
    await engine.release_all("c2")
    assert provider.subscribed == []
    assert engine.health.active_streams == []


async def test_live_candles_ticks_and_10m_fanout(
    setup: tuple[MarketDataEngine, FakeProvider, FakePublisher],
) -> None:
    engine, provider, publisher = setup
    provider.candles[("BTCUSDT", Timeframe.M5)] = [h.candle(0, c="101")]
    await engine.subscribe("five", "BTCUSDT", Timeframe.M5)
    await engine.subscribe("ten", "BTCUSDT", Timeframe.M10)
    await engine.subscribe("eth", "ETHUSDT", Timeframe.M1)
    publisher.clear()

    await provider.push(h.candle(5, c="102", closed=False))
    five = publisher.of_type("market.candle", "five")
    ten = publisher.of_type("market.candle", "ten")
    assert [e["timeframe"] for e in five] == ["5m"]
    assert five[0]["candle"]["time"] == h.at(5) // 1000
    assert five[0]["candle"]["close"] == "102"
    assert five[0]["candle"]["is_closed"] is False
    assert ten[0]["timeframe"] == "10m"
    assert ten[0]["candle"]["time"] == h.at(0) // 1000  # seeded with the 12:00 child
    assert ten[0]["candle"]["open"] == "100"
    assert publisher.of_type("market.candle", "eth") == []  # other symbol untouched

    ticks = publisher.of_type("market.tick", "five")
    assert ticks[0]["price"] == "102"
    assert publisher.of_type("market.tick", "ten") == ticks  # same symbol
    assert publisher.of_type("market.tick", "eth") == []

    publisher.clear()
    await provider.push(h.candle(5, c="102", closed=False))  # duplicate push
    assert publisher.of_type("market.candle") == []


async def test_stale_stream_detection_and_recovery(
    setup: tuple[MarketDataEngine, FakeProvider, FakePublisher],
) -> None:
    engine, provider, publisher = setup
    await engine.subscribe("c1", "ETHUSDT", Timeframe.M1)
    stream = engine.candles.stream("ETHUSDT", Timeframe.M1)
    stream.last_update = time.monotonic() - 1
    publisher.clear()
    engine.check_streams()
    assert publisher.of_type("market.stream", "c1")[-1]["state"] == "stale"
    assert engine.health.stale_streams == ["ETHUSDT:1m"]
    assert engine.health.overall == "degraded"
    assert publisher.broadcasts[-1].data["state"] == "degraded"

    await provider.push(h.candle(6, tf=Timeframe.M1, symbol="ETHUSDT", closed=False))
    assert publisher.of_type("market.stream", "c1")[-1]["state"] == "live"
    assert engine.health.stale_streams == []
    assert publisher.broadcasts[-1].data["state"] == "connected"


async def test_reconnect_triggers_gap_recovery_and_resync(
    setup: tuple[MarketDataEngine, FakeProvider, FakePublisher],
) -> None:
    engine, provider, publisher = setup
    await engine.subscribe("c1", "BTCUSDT", Timeframe.M1)
    await provider.push(h.candle(3, tf=Timeframe.M1, closed=False))

    await provider.set_state("reconnecting")
    assert publisher.of_type("market.stream", "c1")[-1]["state"] == "reconnecting"
    assert publisher.broadcasts[-1].data["state"] == "reconnecting"

    # While disconnected, candles 12:03..12:05 completed on the exchange.
    provider.candles[("BTCUSDT", Timeframe.M1)] = [
        h.candle(m, tf=Timeframe.M1, c=str(200 + m)) for m in (3, 4, 5)
    ] + [h.candle(6, tf=Timeframe.M1, c="206", closed=False)]
    publisher.clear()
    await provider.set_state("connected")
    provider.stats.reconnect_count = 1
    assert provider.on_reconnected is not None
    await provider.on_reconnected()

    stream = engine.candles.stream("BTCUSDT", Timeframe.M1)
    assert sorted(stream.closed) == [h.at(3), h.at(4), h.at(5)]
    assert stream.forming is not None
    assert stream.forming.open_ms == h.at(6)
    resync = publisher.of_type("market.resync", "c1")
    assert resync == [{"symbol": "BTCUSDT", "timeframe": "1m", "reason": "reconnect"}]
    assert engine.health.gap_recoveries == 1
    assert engine.health_snapshot()["reconnect_count"] == 1

    # Live processing resumes and deduplicates against reconciled candles.
    publisher.clear()
    await provider.push(h.candle(5, tf=Timeframe.M1, c="1"))  # stale replay of a closed candle
    assert publisher.of_type("market.candle") == []


async def test_history_native_and_10m(
    setup: tuple[MarketDataEngine, FakeProvider, FakePublisher],
) -> None:
    engine, provider, _ = setup
    provider.candles[("BTCUSDT", Timeframe.M5)] = [h.candle(m) for m in (-20, -15, -10, -5, 0)] + [
        h.candle(5, closed=False)
    ]
    btc = engine.symbols.get("BTCUSDT")
    native = await engine.candles.history(btc, Timeframe.M5, limit=3)
    assert [c.open_ms for c in native] == [h.at(-5), h.at(0), h.at(5)]
    assert native[-1].is_closed is False

    ten = await engine.candles.history(btc, Timeframe.M10, limit=10)
    assert [c.open_ms for c in ten] == [h.at(-20), h.at(-10), h.at(0)]
    assert [c.is_closed for c in ten] == [True, True, False]
    assert any(call.startswith("candles:BTCUSDT:5m") for call in provider.calls)


async def test_symbol_delisting_releases_streams_and_notifies(
    setup: tuple[MarketDataEngine, FakeProvider, FakePublisher],
) -> None:
    engine, provider, publisher = setup
    await engine.subscribe("c1", "ETHUSDT", Timeframe.M15)
    provider.symbols = [s for s in provider.symbols if s.symbol != "ETHUSDT"]
    await engine.symbols.refresh()
    assert publisher.of_type("market.stream", "c1")[-1]["state"] == "unavailable"
    assert provider.subscribed == []
    with pytest.raises(SymbolUnavailable):
        await engine.subscribe("c1", "ETHUSDT", Timeframe.M15)


async def test_rest_outage_raises_structured_error_without_crashing(
    setup: tuple[MarketDataEngine, FakeProvider, FakePublisher],
) -> None:
    engine, provider, _ = setup
    provider.fail_rest = True
    with pytest.raises(BingXUnavailable):
        await engine.candles.history(engine.symbols.get("BTCUSDT"), Timeframe.M1, limit=10)
    # Subscriptions/streaming still work during a REST outage.
    await engine.subscribe("c1", "BTCUSDT", Timeframe.M1)
    await provider.push(h.candle(6, tf=Timeframe.M1, closed=False))


async def test_time_based_finalization_asks_rest(
    setup: tuple[MarketDataEngine, FakeProvider, FakePublisher], monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, provider, publisher = setup
    await engine.subscribe("c1", "BTCUSDT", Timeframe.M1)
    await provider.push(h.candle(5, tf=Timeframe.M1, c="150", closed=False))
    # Quiet market: no newer push, but 12:06 + grace has passed.
    monkeypatch.setattr("app.market_data.engine.now_ms", lambda: h.at(6.5))
    provider.candles[("BTCUSDT", Timeframe.M1)] = [h.candle(5, tf=Timeframe.M1, c="151")]
    publisher.clear()
    engine.check_streams()
    for task in list(engine._tasks):
        await task
    closed = [e for e in publisher.of_type("market.candle", "c1") if e["candle"]["is_closed"]]
    assert closed
    assert closed[0]["candle"]["close"] == "151"


async def test_stale_and_recovery_reach_synthetic_10m_consumers(
    setup: tuple[MarketDataEngine, FakeProvider, FakePublisher],
) -> None:
    engine, provider, publisher = setup
    await engine.subscribe("ten", "BTCUSDT", Timeframe.M10)
    engine.candles.stream("BTCUSDT", Timeframe.M5).last_update = time.monotonic() - 1
    publisher.clear()
    engine.check_streams()
    assert publisher.of_type("market.stream", "ten")[-1]["state"] == "stale"
    await provider.push(h.candle(5, closed=False))
    assert publisher.of_type("market.stream", "ten")[-1] == {
        "symbol": "BTCUSDT",
        "timeframe": "10m",
        "state": "live",
    }


async def test_status_broadcast_follows_rest_reachability(
    setup: tuple[MarketDataEngine, FakeProvider, FakePublisher],
) -> None:
    engine, provider, publisher = setup
    # Exchange socket reconnects while REST is still failing, then REST recovers.
    engine.health.record_rest(False, "ConnectError")
    assert publisher.broadcasts[-1].data["state"] == "degraded"
    await provider.set_state("reconnecting")
    await provider.set_state("connected")
    assert publisher.broadcasts[-1].data["state"] == "degraded"
    engine.health.record_rest(True, None)
    assert publisher.broadcasts[-1].data["state"] == "connected"
    count = len(publisher.broadcasts)
    engine.health.record_rest(True, None)  # no change -> no extra broadcast
    assert len(publisher.broadcasts) == count
