"""Integrity tests for Phase 5 lower-timeframe research (gate G12: no look-ahead, no repaint,
split separation, cost arithmetic)."""

from __future__ import annotations

import itertools
import math
import random

import pytest

from app.research.ltf5 import data, sim, strategy
from app.research.ltf5.data import DEV_END_MS, HOLDOUT_START_MS, VAL_END_MS, Series


def synthetic(n: int = 4000, seed: int = 3, tf: str = "5m", start: int = 0) -> Series:
    rng = random.Random(seed)  # noqa: S311 - deterministic test data
    s = Series("TESTUSDT", tf)
    price = 100.0
    drift = 0.0
    for k in range(n):
        if k % 400 == 0:
            drift = rng.choice((-1, 1)) * 0.0004
        o = price
        c = max(1.0, o * (1 + drift + rng.gauss(0, 0.003)))
        h = max(o, c) * (1 + abs(rng.gauss(0, 0.0015)))
        lo = min(o, c) * (1 - abs(rng.gauss(0, 0.0015)))
        s.append(start + k * s.step, o, h, lo, c, 100 + rng.random() * 50)
        price = c
    return s


def prefix(s: Series, n: int) -> Series:
    p = Series(s.symbol, s.timeframe)
    for k in range(n):
        p.append(s.t[k], s.o[k], s.h[k], s.lo[k], s.c[k], s.v[k])
    return p


def test_candidates_are_causal_no_lookahead_no_repaint() -> None:
    full = synthetic()
    ctx = data.aggregate(full, "1h")
    every = strategy.candidates(full, ctx)
    assert len(every) > 20
    for cut in (1500, 2600, 3300):
        part = prefix(full, cut)
        ctx_part = data.aggregate(part, "1h")
        early = strategy.candidates(part, ctx_part)
        # identical decisions for every candle that existed at the cut: nothing repaints
        assert early == [c for c in every if c.i < cut]


def test_context_uses_only_closed_context_candles() -> None:
    full = synthetic()
    ctx_series = data.aggregate(full, "1h")
    ctx = strategy.Context(ctx_series)
    close_ms = full.t[999] + full.step
    ctx.advance(close_ms)
    assert ctx.last_close_time is not None
    assert ctx.last_close_time <= close_ms
    # the next context candle closes strictly after the execution close
    k = ctx.k
    assert k == len(ctx_series) or ctx_series.t[k] + ctx_series.step > close_ms


def test_aggregation_uses_complete_buckets_only() -> None:
    s = synthetic(n=60, tf="5m")
    holed = Series(s.symbol, "5m")
    for k in range(60):
        if k != 7:  # drop one 5m candle -> its 1h bucket must be skipped
            holed.append(s.t[k], s.o[k], s.h[k], s.lo[k], s.c[k], s.v[k])
    agg = data.aggregate(holed, "1h")
    assert len(agg) == 4  # 60 x 5m = 5 hours; the hour holding the hole is dropped
    assert all(t % 3_600_000 == 0 for t in agg.t)


def test_split_boundaries_are_ordered_and_holdout_is_locked() -> None:
    assert DEV_END_MS < VAL_END_MS == HOLDOUT_START_MS
    with pytest.raises(data.HoldoutLockedError):
        data.load("BTCUSDT", "5m", end_ms=None)


def _long_plan(entry: float = 100.0, stop: float = 99.0) -> strategy.Plan:
    r = entry - stop
    return strategy.Plan(entry, stop, r, (entry + r, entry + 2 * r, entry + 3 * r))


def _cand(i: int, plan: strategy.Plan, limit: strategy.Plan | None = None) -> strategy.Candidate:
    return strategy.Candidate(
        i=i,
        time=0,
        side=1,
        atr=1.0,
        market=plan,
        limit=limit or plan,
        ctx_dir=1,
        disp=True,
        candle=True,
        sweep=False,
        vol=True,
        volband=True,
        ext_ok=True,
        too_wide=False,
        hour=0,
        atr_pct=50.0,
        ctx_strength=1.0,
    )


def _series(rows: list[tuple[float, float, float, float]]) -> Series:
    s = Series("TESTUSDT", "5m")
    for k, (o, h, lo, c) in enumerate(rows):
        s.append(k * 300_000, o, h, lo, c, 1.0)
    return s


def test_stop_first_when_stop_and_target_share_a_candle() -> None:
    s = _series([(100, 100, 100, 100), (100, 103.5, 98.5, 101)])
    tr = sim.simulate(s, _cand(0, _long_plan()), sim.Config(floor=1.0), tick=0.01)
    assert tr is not None
    assert tr.exit_reason == "stop"
    assert tr.gross_r == pytest.approx(-1.0)


def test_gap_through_stop_exits_at_open() -> None:
    s = _series([(100, 100, 100, 100), (97.0, 97.5, 96.5, 97.2)])
    tr = sim.simulate(s, _cand(0, _long_plan()), sim.Config(floor=1.0), tick=0.01)
    assert tr is not None
    assert tr.gross_r == pytest.approx(-3.0)


def test_cost_arithmetic_market_entry_full_target_run() -> None:
    s = _series([(100, 100, 100, 100), (100, 103.2, 99.5, 103)])
    tr = sim.simulate(s, _cand(0, _long_plan()), sim.Config(floor=1.0), tick=0.01)
    assert tr is not None
    assert tr.exit_reason == "tp3" and tr.targets_hit == 3
    assert tr.gross_r == pytest.approx(2.0)
    base = sim.BASE
    fees = base.taker * 100 + base.maker * (101 + 102 + 103) / 3
    slip = base.slip * 100
    assert tr.fee_r == pytest.approx(2.0 - fees / 1.0)
    assert tr.net_r == pytest.approx(2.0 - (fees + slip) / 1.0)
    assert tr.net_high_r < tr.net_r < tr.fee_r < tr.gross_r


def test_limit_fills_only_through_the_price_and_cancels_when_the_move_leaves() -> None:
    plan = _long_plan(100.0, 99.0)
    touch_only = _series([(100, 100, 100, 100), (100.5, 100.6, 100.0, 100.4)] + [(100.4,) * 4] * 3)
    assert sim.simulate(touch_only, _cand(0, plan), sim.Config(limit=True, floor=1.0), 0.01) is None
    left = _series([(100, 100, 100, 100), (100.5, 101.2, 100.3, 101.1)])
    assert sim.simulate(left, _cand(0, plan), sim.Config(limit=True, floor=1.0), 0.01) is None
    through = _series(
        [(100, 100, 100, 100), (100.2, 100.3, 99.95, 100.1), (100.1, 103.2, 100, 103)]
    )
    tr = sim.simulate(through, _cand(0, plan), sim.Config(limit=True, floor=1.0), 0.01)
    assert tr is not None and tr.targets_hit == 3


def test_cost_floor_rejects_trades_dominated_by_friction() -> None:
    tiny = _long_plan(100.0, 99.9)  # 0.1% risk vs ~0.14% round trip
    s = _series([(100, 100, 100, 100), (100, 100.4, 99.95, 100.3)])
    assert sim.simulate(s, _cand(0, tiny), sim.Config(floor=0.20), tick=0.01) is None


def test_one_position_at_a_time_and_no_reentry_on_the_same_setup() -> None:
    s = synthetic(n=3000)
    ctx = data.aggregate(s, "1h")
    cands = strategy.candidates(s, ctx)
    trades = sim.run(s, cands, sim.Config(ctx=False, floor=1.0), 0.01, 0, 2**62)
    for a, b in itertools.pairwise(trades):
        assert b.signal_time > a.exit_time - s.step  # next trigger after the previous exit
    assert all(math.isfinite(t.net_r) for t in trades)


def test_score_is_component_share_not_probability() -> None:
    c = _cand(0, _long_plan())
    assert 0 <= c.score() <= 100
    assert set(c.flags()) == {"ctx", "disp", "candle", "sweep", "vol", "volband", "ext"}
