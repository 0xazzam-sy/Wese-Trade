"""Snapshot generation, readiness, serialization and the no-signal guarantee."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

import pytest

from app.analysis.engine import MarketAnalyzer, analyze_history
from app.analysis.models import MtfFrame
from app.analysis.serialize import snapshot_payload
from tests.analysis.helpers import load_fixture

# Phase 4 concepts that must not exist anywhere in Phase 3 output.
FORBIDDEN_KEYS = {
    "signal",
    "label",
    "buy",
    "sell",
    "strong_buy",
    "strong_sell",
    "entry",
    "stop_loss",
    "sl",
    "tp",
    "tp1",
    "tp2",
    "tp3",
    "take_profit",
    "take_profits",
    "risk_reward",
    "rr",
    "confidence",
    "probability",
}
FORBIDDEN_VALUES = {"BUY", "SELL", "STRONG_BUY", "STRONG_SELL"}


def _walk(value: Any, path: str = "") -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    if isinstance(value, dict):
        for k, v in value.items():
            out.append((k, v))
            out += _walk(v, f"{path}.{k}")
    elif isinstance(value, list):
        for v in value:
            out += _walk(v, path)
    return out


def _ready_payload() -> dict[str, Any]:
    candles, tick = load_fixture("okx_btcusdt_5m")
    analyzer, _ = analyze_history("BTCUSDT", candles[0].timeframe, candles[:-1], tick_size=tick)
    forming = replace(candles[-1], is_closed=False)
    frame = MtfFrame("15m", False, None, None, None, None, None)
    return snapshot_payload(analyzer.snapshot(forming, context=[frame], include_debug=True))


def test_insufficient_history_is_not_ready() -> None:
    candles, tick = load_fixture("okx_btcusdt_5m")
    analyzer = MarketAnalyzer("BTCUSDT", candles[0].timeframe, tick_size=tick)
    for c in candles[:120]:
        analyzer.update(c)
    snap = analyzer.snapshot()
    assert snap.analysis_ready is False and snap.reason == "insufficient_history"
    assert snap.trend is None and snap.swing_structure is None
    assert snapshot_payload(snap)["candles_analyzed"] == 120


def test_ready_snapshot_has_every_section() -> None:
    payload = _ready_payload()
    assert payload["analysis_ready"] is True and payload["reason"] is None
    for section in (
        "trend",
        "regime",
        "volatility",
        "momentum",
        "volume",
        "candle",
        "forming_candle",
        "swing_structure",
        "internal_structure",
        "liquidity",
        "fair_value_gaps",
        "order_blocks",
        "premium_discount",
        "multi_timeframe",
        "developing",
        "counts",
        "debug",
    ):
        assert section in payload, section
    assert [e["period"] for e in payload["trend"]["emas"]] == [20, 50, 100, 200]
    assert payload["regime"]["directional"] and payload["regime"]["volatility"]
    assert payload["forming_candle"]["status"] == "developing"
    assert payload["candle"]["status"] == "confirmed"
    assert payload["multi_timeframe"]["directional_alignment"] == "unavailable"
    assert 0 <= payload["momentum"]["rsi"] <= 100
    times = [e["time"] for e in payload["swing_structure"]["events"]]
    assert times == sorted(times)
    for gap in payload["fair_value_gaps"]:
        assert gap["top"] > gap["bottom"]
        assert gap["mid"] == pytest.approx((gap["top"] + gap["bottom"]) / 2)
        assert 0 <= gap["quality"] <= 100
    for block in payload["order_blocks"]:
        assert 0 <= block["quality"] <= 100
    json.dumps(payload)  # JSON-safe


def test_no_signal_or_trade_plan_fields_anywhere() -> None:
    payload = _ready_payload()
    for key, value in _walk(payload):
        assert key.lower() not in FORBIDDEN_KEYS, key
        if isinstance(value, str):
            assert value.upper() not in FORBIDDEN_VALUES, value


def test_debug_is_opt_in() -> None:
    candles, tick = load_fixture("okx_btcusdt_5m")
    analyzer, _ = analyze_history("BTCUSDT", candles[0].timeframe, candles, tick_size=tick)
    assert analyzer.snapshot().debug is None
    debug = analyzer.snapshot(include_debug=True).debug
    assert debug is not None and debug["pivot_confirmation_bars"] == {"swing": 5, "internal": 2}


def test_history_rows_are_bounded_and_ordered() -> None:
    candles, tick = load_fixture("okx_btcusdt_5m")
    analyzer, _ = analyze_history("BTCUSDT", candles[0].timeframe, candles, tick_size=tick)
    rows = list(analyzer.rows)
    assert len(rows) == analyzer.config.history_rows
    assert [r["time"] for r in rows] == sorted(r["time"] for r in rows)
    assert rows[-1]["regime"] is not None
