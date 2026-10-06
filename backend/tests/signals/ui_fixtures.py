"""Deterministic UI fixtures for the chart BUY/SELL markers (frontend tests + E2E).

The frozen forward strategy is replayed on the real OKX fixture candles exactly like the
live forward-test service (lifecycle first, then evaluation of the closed candle), and the
confirmed signals are exported with the same `signal_payload` the API and WebSocket send.
Nothing is hand-written: `test_ui_fixtures_match_engine` fails if the committed JSON ever
drifts from the engine output.

    python -m tests.signals.ui_fixtures   # (from backend/) regenerate the frontend fixture
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.analysis.engine import MarketAnalyzer
from app.forward_test.candidate import candidate
from app.forward_test.evaluate import LiveContext, evaluate_candle
from app.market_data.timeframes import Timeframe
from app.signal_engine.lifecycle import SignalTracker
from app.signal_engine.models import Signal
from app.signal_engine.serialize import signal_payload
from tests.signals.test_frozen_strategy_fixtures import CTX, FROZEN, _load

OUTPUT = (
    Path(__file__).resolve().parents[3]
    / "frontend"
    / "src"
    / "test"
    / "fixtures"
    / "frozen-signals.json"
)
BARS_BEFORE = 150  # chart history shown before the confirmation candle
BARS_AFTER = 12  # and after it (lifecycle advanced honestly through these bars)


def replay(name: str) -> dict[str, Any]:
    frames, tick, trigger = _load(name)
    v = candidate()
    base = MarketAnalyzer("ETHUSDT", Timeframe.M15, tick_size=tick)
    ctx = {tf: MarketAnalyzer("ETHUSDT", tf, tick_size=tick) for tf in CTX}
    pos = dict.fromkeys(CTX, 0)
    confirmed: list[Signal] = []
    at_confirmation: dict[str, Any] | None = None

    def sink(kind: str, signal: Signal) -> None:
        nonlocal at_confirmation
        if kind == "confirmed":
            confirmed.append(signal)
            if signal.trigger_time == trigger:
                at_confirmation = signal_payload(signal)

    tracker = SignalTracker(
        "ETHUSDT", "15m", v.tracker_config(), step_seconds=Timeframe.M15.seconds, sink=sink
    )
    m15 = frames[Timeframe.M15]
    index = next(i for i, c in enumerate(m15) if int(c.open_time.timestamp()) == trigger)
    end = index + BARS_AFTER
    for i, candle in enumerate(m15[: end + 1]):
        close_ms = candle.open_ms + Timeframe.M15.milliseconds
        for tf in CTX:
            series = frames[tf]
            while pos[tf] < len(series) and series[pos[tf]].open_ms + tf.milliseconds <= close_ms:
                ctx[tf].update(series[pos[tf]])
                pos[tf] += 1
        base.update(candle)
        bar = base.series.last
        tracker.on_bar(bar)  # lifecycle first, exactly like the live service
        if i < index - BARS_BEFORE:
            continue  # warm-up only (signals only from the shown window)
        ev = evaluate_candle(
            v,
            base,
            [ctx[tf].frame() for tf in CTX],
            LiveContext(market_stale=False, symbol_active=True),
            strategy_version=FROZEN,
        )
        tracker.on_evaluation(ev, bar)
    target = [s for s in confirmed if s.trigger_time == trigger]
    assert len(target) == 1 and at_confirmation is not None
    candles = [
        {
            "time": int(c.open_time.timestamp()),
            "open": str(c.open),
            "high": str(c.high),
            "low": str(c.low),
            "close": str(c.close),
            "volume": str(c.volume),
            "is_closed": True,
        }
        for c in m15[index - BARS_BEFORE : end + 1]
    ]
    return {
        "symbol": "ETHUSDT",
        "timeframe": "15m",
        "trigger_time": trigger,
        "candles": candles,
        "signal_at_confirmation": at_confirmation,
        "signal": signal_payload(target[0]),
        # every signal the engine confirmed in the shown window (oldest first), with the
        # lifecycle state reached at the last shown candle: what persistence would hold
        "signals": [signal_payload(s) for s in confirmed],
    }


def build() -> dict[str, Any]:
    return {
        "_source": "backend/tests/signals/ui_fixtures.py (real engine replay; do not edit)",
        "strategy_version": FROZEN,
        "buy": replay("frozen_buy"),
        "sell": replay("frozen_sell"),
    }


def render() -> str:
    return json.dumps(build(), ensure_ascii=False, indent=1, sort_keys=True) + "\n"


if __name__ == "__main__":
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(render(), encoding="utf-8")
    print(f"wrote {OUTPUT}")
