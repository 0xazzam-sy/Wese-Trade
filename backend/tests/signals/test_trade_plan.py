"""Trade plan: entry models, structure-aware stops, targets, R:R, rejections."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from app.analysis.enums import ZoneType
from app.analysis.models import AnalysisSnapshot
from app.signal_engine.config import DEFAULT_SIGNAL_CONFIG, SignalConfig
from app.signal_engine.enums import EntryModel, SetupFamily, Side
from app.signal_engine.models import TradePlan, Trigger
from app.signal_engine.rules import Setup
from app.signal_engine.scoring import Ctx
from app.signal_engine.trade_plan import PlanRejectedError, build_plan
from tests.signals.builders import T, bars, make_snapshot, must, order_block

TRIG = Trigger("t", T, "internal", "BOS", "bullish", 70.0, 1.6, 99.5)


def plan(
    anchors: list[tuple[float, str]],
    *,
    snapshot: AnalysisSnapshot | None = None,
    cfg: SignalConfig = DEFAULT_SIGNAL_CONFIG,
    side: Side = Side.LONG,
    **setup: Any,
) -> TradePlan:
    ctx = Ctx(snapshot or make_snapshot(), side, bars(), 0.01, cfg)
    return build_plan(ctx, Setup(SetupFamily.TREND_CONTINUATION, side, TRIG, anchors, **setup))


def test_market_entry_and_structure_stop_with_buffer() -> None:
    p = plan([(98.0, "internal_protected")])
    assert p.entry_model is EntryModel.MARKET
    assert p.entry_low == p.entry_high == p.preferred_entry == 100.0
    buffer = max(3 * 0.01, 0.1 * 1.0)
    assert p.stop == pytest.approx(98.0 - buffer)
    assert p.stop_source == "internal_protected"
    assert p.risk == pytest.approx(100.0 - p.stop)


def test_zone_entry_uses_zone_midpoint() -> None:
    p = plan([(98.0, "x")], entry_model=EntryModel.ZONE, zone_edge=99.4)
    assert p.entry_model is EntryModel.ZONE
    assert (p.entry_low, p.entry_high, p.preferred_entry) == (99.4, 100.0, 99.7)


def test_tight_structure_is_widened_to_noise_floor() -> None:
    p = plan([(99.8, "internal_protected")])
    assert p.stop_source.endswith("+floor")
    cfg = DEFAULT_SIGNAL_CONFIG
    floor = max(
        cfg.min_stop_atr * 1.0, cfg.min_risk_cost_multiple * cfg.round_trip_cost_rate() * 100.0
    )
    assert p.risk == pytest.approx(floor)  # noise floor or cost floor, whichever is larger


def test_far_anchor_skipped_and_absurd_stop_rejected() -> None:
    p = plan([(90.0, "too_far"), (98.0, "ok")])
    assert p.stop_source == "ok"
    with pytest.raises(PlanRejectedError):
        plan([(90.0, "too_far")])
    with pytest.raises(PlanRejectedError):
        plan([])  # no anchor: no rational stop -> no signal


def test_cost_floor_rejects_cost_dominated_trades() -> None:
    snap = make_snapshot()
    tiny_atr = replace(
        snap, volatility=replace(must(snap.volatility), atr=0.05)
    )  # costs >> structure
    with pytest.raises(PlanRejectedError, match="تكلفة"):
        plan([(99.9, "x")], snapshot=tiny_atr)


def test_targets_are_ordered_distinct_and_sourced() -> None:
    p = plan([(98.0, "internal_protected")])
    prices = [p.preferred_entry, *(t.price for t in p.targets)]
    assert prices == sorted(prices) and len(set(prices)) == 4
    assert p.targets[0].source == "liquidity"  # the buy-side pool at 104, front-run
    assert p.targets[0].price < 104.0
    for t in p.targets:
        assert t.rr == pytest.approx((t.price - p.preferred_entry) / p.risk, abs=0.01)
    assert p.rr()[1] >= DEFAULT_SIGNAL_CONFIG.min_tp2_rr


def test_extension_targets_when_structure_is_missing() -> None:
    snap = make_snapshot(liquidity=None, premium_discount=None)
    snap = replace(
        snap,
        swing_structure=replace(must(snap.swing_structure), break_high=None),
        internal_structure=replace(must(snap.internal_structure), break_high=None),
    )
    p = plan([(98.0, "x")], snapshot=snap)
    assert [t.source for t in p.targets] == ["extension"] * 3
    assert [t.rr for t in p.targets] == [1.0, 2.0, 3.0]


def test_headroom_rejects_opposing_level_too_close() -> None:
    blocked = make_snapshot(order_blocks=(order_block(ZoneType.BEARISH_OB, 101.6, 100.8),))
    with pytest.raises(PlanRejectedError):
        plan([(98.0, "x")], snapshot=blocked)


def test_short_plan_mirrors() -> None:
    snap = make_snapshot()
    short = replace(snap, swing_structure=replace(must(snap.swing_structure), break_low=94.0))
    p = plan([(102.0, "internal_protected")], snapshot=short, side=Side.SHORT)
    prices = [p.preferred_entry, *(t.price for t in p.targets)]
    assert prices == sorted(prices, reverse=True)
    assert p.stop > p.preferred_entry
