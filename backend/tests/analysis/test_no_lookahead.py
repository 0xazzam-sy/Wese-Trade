"""No-lookahead, no-repaint and replay consistency (the most important analysis tests).

Uses REAL OKX candles (tests/analysis/data) and the DEFAULT production config.

1. Future independence: output known at candle N is identical whatever happens after N
   (the future is replaced by a mirrored, completely different path).
2. No repaint: once a confirmed fact (pivot, BOS/CHoCH, sweep, FVG, OB) appears, it never
   changes and never disappears while it is within the retention window.
3. Replay == live: an analyzer fed candle-by-candle (live) produces exactly the same
   snapshot at N as a fresh analyzer replaying candles[:N] (historical).
4. Timestamps: nothing is confirmed before the data that defines it exists.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from app.analysis.config import DEFAULT_CONFIG
from app.analysis.engine import AnalysisOrderError, MarketAnalyzer
from app.analysis.serialize import snapshot_payload
from app.market_data.models import Candle
from tests.analysis.helpers import load_fixture

FIXTURES = ["okx_btcusdt_5m", "okx_solusdt_1m"]
FIXED_TIME = datetime(2030, 1, 1, tzinfo=UTC)


def facts(analyzer: MarketAnalyzer) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for kind, items in analyzer.confirmed_facts().items():
        for item in items:
            key = item.id if hasattr(item, "id") else item[0]
            out[f"{kind}:{key}"] = item
    return out


def mirrored_future(candles: list[Candle], n: int) -> list[Candle]:
    pivot = candles[n].close
    out = candles[: n + 1]
    for c in candles[n + 1 :]:
        out.append(
            replace(
                c,
                open=2 * pivot - c.open,
                high=2 * pivot - c.low,
                low=2 * pivot - c.high,
                close=2 * pivot - c.close,
                volume=c.volume * Decimal("1.7"),
            )
        )
    return out


def replay(candles: list[Candle], tick: float) -> tuple[MarketAnalyzer, list[dict[str, Any]]]:
    analyzer = MarketAnalyzer(candles[0].symbol, candles[0].timeframe, tick_size=tick)
    steps: list[dict[str, Any]] = []
    for c in candles:
        analyzer.update(c)
        steps.append(facts(analyzer))
    return analyzer, steps


@pytest.mark.parametrize("name", FIXTURES)
def test_output_at_n_does_not_depend_on_future(name: str) -> None:
    candles, tick = load_fixture(name)
    _, real_steps = replay(candles, tick)
    for n in (320, 400, 480, 560, 640):
        _, alt_steps = replay(mirrored_future(candles, n), tick)
        assert real_steps[n] == alt_steps[n], f"facts at {n} depend on the future"
        # And everything the real run knew at n is still identical later in the alt run
        # unless the alt future legitimately pruned it (only by age).
        for key, value in real_steps[n].items():
            later = alt_steps[n + 40].get(key)
            assert later is None or later == value


@pytest.mark.parametrize("name", FIXTURES)
def test_confirmed_facts_never_repaint(name: str) -> None:
    candles, tick = load_fixture(name)
    _, steps = replay(candles, tick)
    first_seen: dict[str, tuple[int, Any]] = {}
    for step, current in enumerate(steps):
        for key, value in current.items():
            if key in first_seen:
                assert first_seen[key][1] == value, f"{key} changed after confirmation"
            else:
                first_seen[key] = (step, value)
        previous = steps[step - 1] if step else {}
        for key in previous.keys() - current.keys():
            seen_at = first_seen[key][0]
            assert step - seen_at >= 100, f"{key} vanished only {step - seen_at} candles later"
    kinds = {k.split(":", 1)[0] for k in first_seen}
    assert {"pivots", "events", "fvgs"} <= kinds


@pytest.mark.parametrize("name", FIXTURES)
def test_live_incremental_equals_historical_replay(name: str) -> None:
    candles, tick = load_fixture(name)
    live = MarketAnalyzer(candles[0].symbol, candles[0].timeframe, tick_size=tick)
    checkpoints = {299, 300, 450, 699}
    for i, c in enumerate(candles):
        live.update(c)
        if i not in checkpoints:
            continue
        historical = MarketAnalyzer(c.symbol, c.timeframe, tick_size=tick)
        for old in candles[: i + 1]:
            historical.update(old)
        forming = replace(candles[i + 1], is_closed=False) if i + 1 < len(candles) else None
        a = snapshot_payload(live.snapshot(forming, generated_at=FIXED_TIME, context=[]))
        b = snapshot_payload(historical.snapshot(forming, generated_at=FIXED_TIME, context=[]))
        assert a == b
        assert a["analysis_ready"] is (i + 1 >= DEFAULT_CONFIG.min_candles)


@pytest.mark.parametrize("name", FIXTURES)
def test_no_future_timestamps(name: str) -> None:
    candles, tick = load_fixture(name)
    analyzer = MarketAnalyzer(candles[0].symbol, candles[0].timeframe, tick_size=tick)
    for c in candles:
        analyzer.update(c)
        close_time = c.open_ms // 1000 + c.timeframe.seconds
        state = analyzer.confirmed_facts()
        for item in [*state["pivots"], *state["events"]]:
            assert item.time < item.confirmed_time <= close_time
        for pivot in state["pivots"]:
            right = analyzer.config.swing_right if pivot.layer.value == "swing" else 2
            assert pivot.confirmed_index - pivot.index == right
        for zone in analyzer.fvgs.gaps:
            assert zone.confirmed_time <= close_time
        for sweep in analyzer.liquidity.sweeps:
            assert sweep.confirmed_time <= close_time


def test_developing_features_may_change_but_never_touch_confirmed_state() -> None:
    candles, tick = load_fixture("okx_btcusdt_5m")
    analyzer = MarketAnalyzer(candles[0].symbol, candles[0].timeframe, tick_size=tick)
    for c in candles[:600]:
        analyzer.update(c)
    before = facts(analyzer)
    nxt = candles[600]
    up = replace(nxt, is_closed=False, high=nxt.high * 2, close=nxt.high * 2)
    down = replace(nxt, is_closed=False, low=nxt.low / 2, close=nxt.low / 2)
    snap_up = analyzer.snapshot(up, context=[])
    snap_down = analyzer.snapshot(down, context=[])
    assert facts(analyzer) == before  # forming candles never mutate confirmed state
    assert snap_up.developing is not None and snap_down.developing is not None
    up_breaks = [b.direction.value for b in snap_up.developing.swing_breaks]
    down_breaks = [b.direction.value for b in snap_down.developing.swing_breaks]
    assert "bullish" in up_breaks and "bearish" in down_breaks
    assert all(b.status.value == "developing" for b in snap_up.developing.swing_breaks)


def test_out_of_order_candles_are_rejected() -> None:
    candles, tick = load_fixture("okx_btcusdt_5m")
    analyzer = MarketAnalyzer(candles[0].symbol, candles[0].timeframe, tick_size=tick)
    analyzer.update(candles[1])
    with pytest.raises(AnalysisOrderError):
        analyzer.update(candles[0])
    with pytest.raises(ValueError, match="closed candles only"):
        analyzer.update(replace(candles[2], is_closed=False))
