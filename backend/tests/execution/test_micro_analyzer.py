"""Live microstructure health and the real incremental execution analyzer."""

from __future__ import annotations

from typing import Any

from app.analysis.engine import MarketAnalyzer
from app.execution import engine
from app.execution.analyzer import ExecAnalyzer
from app.execution.micro import MicroFeed
from app.market_data.timeframes import Timeframe
from tests.forward_test.helpers import candles


class FakeSocket:
    def __init__(self, name: str, url: str) -> None:
        self.state = "connected"
        self.subs: set[tuple[str, str]] = set()

    def set_handlers(self, **_: Any) -> None:
        return None

    def start(self) -> None:
        return None

    def subscribe(self, channel: str, inst: str) -> None:
        self.subs.add((channel, inst))

    def unsubscribe(self, channel: str, inst: str) -> None:
        self.subs.discard((channel, inst))

    async def close(self) -> None:
        return None


def book(bid: str, ask: str, bsz: str = "5", asz: str = "1") -> dict[str, Any]:
    return {
        "arg": {"channel": "books5", "instId": "BTC-USDT-SWAP"},
        "data": [{"instId": "BTC-USDT-SWAP", "bids": [[bid, bsz, "0", "1"]] * 5,
                  "asks": [[ask, asz, "0", "1"]] * 5, "ts": "1"}],
    }  # fmt: skip


def trade(side: str, sz: str = "1") -> dict[str, Any]:
    return {
        "arg": {"channel": "trades", "instId": "BTC-USDT-SWAP"},
        "data": [{"instId": "BTC-USDT-SWAP", "px": "100", "sz": sz, "side": side, "ts": "1"}],
    }


def test_micro_health_states_and_refcount() -> None:
    now = [1000.0]
    feed = MicroFeed("wss://x", socket_factory=FakeSocket, clock=lambda: now[0])
    assert feed.snapshot("BTCUSDT").status == "unavailable"
    feed.acquire("BTCUSDT")
    feed.acquire("BTCUSDT")
    sock = feed._socket
    assert ("books5", "BTC-USDT-SWAP") in sock.subs
    feed.on_message(book("100.0", "100.1"))
    feed.on_message(trade("buy", "3"))
    feed.on_message(trade("sell", "1"))
    snap = feed.snapshot("BTCUSDT")
    assert snap.status == "ok" and snap.flow_imbalance == 0.5
    assert snap.book_imbalance is not None and snap.book_imbalance > 0
    feed.on_message(book("100.0", "101.0"))  # spread x10 the normal one
    assert feed.snapshot("BTCUSDT").status == "degraded"
    now[0] += 20  # no book update for 20 s
    assert feed.snapshot("BTCUSDT").status == "stale"
    feed.release("BTCUSDT")
    assert sock.subs  # still referenced once
    feed.release("BTCUSDT")
    assert not sock.subs


def test_real_analyzer_features_are_incremental_and_complete() -> None:
    an = MarketAnalyzer("BTCUSDT", Timeframe.M5, tick_size=0.1)
    ex = ExecAnalyzer()
    data = candles(400, Timeframe.M5)
    for c in data[:300]:
        an.update(c)
    ex.sync(an.series.tail(len(an.series)))
    assert ex.count == 300
    for c in data[300:]:
        an.update(c)
        assert ex.update(an.series.last)
        assert not ex.update(an.series.last)  # duplicate close ignored
    f = ex.features(an.series.last, an.snapshot(None), an.tick)
    assert f.atr > 0 and f.ema20 is not None and f.ema200 is not None
    assert f.index == an.series.last.index and f.prev_close == float(data[-2].close)
    overlay = ex.overlay(f.close)
    assert set(overlay["ema"]) == {"20", "50", "200"}
    assert all(lv["grade"] in ("strong", "medium", "weak") for lv in overlay["levels"])
    # a usable evaluation comes out of real features
    ev = engine.evaluate("BTCUSDT", "5m", f, None)
    assert ev.decision.value == "NO_SETUP"
