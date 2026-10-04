"""SignalEngine: eligibility, independent bull/bear scoring, neutral, caps, penalties, families."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from app.analysis.enums import (
    LiquiditySide,
    PremiumDiscountZone,
    StructureEventType,
    StructureLayer,
    VolatilityRegime,
    ZoneType,
)
from app.analysis.models import AnalysisSnapshot, DevelopingBreak, DevelopingFeatures
from app.signal_engine.config import DEFAULT_SIGNAL_CONFIG, SignalConfig, strategy_version
from app.signal_engine.engine import NEUTRAL_TEXT, SignalEngine
from app.signal_engine.enums import SetupFamily, Side, SignalClass
from app.signal_engine.models import Component, SignalEvaluation, Trigger
from app.signal_engine.scoring import Ctx, Scored, finalize, score_trigger_cluster
from tests.signals.builders import (
    BEAR,
    BULL,
    NEUTRAL,
    T,
    bars,
    candle,
    event,
    frame,
    make_input,
    make_snapshot,
    must,
    order_block,
    pool,
    structure,
    sweep,
)

ENGINE = SignalEngine()


def evaluate(snapshot: AnalysisSnapshot | None = None, **kw: Any) -> SignalEvaluation:
    return ENGINE.evaluate(make_input(snapshot, **kw))


# --- eligibility gate ---------------------------------------------------------------------
@pytest.mark.parametrize(
    ("snapshot_changes", "input_changes", "reason"),
    [
        ({"analysis_ready": False}, {}, "not_ready"),
        ({}, {"market_stale": True}, "stale"),
        ({}, {"symbol_active": False}, "inactive"),
        ({"volatility": None}, {}, None),
        ({"swing_structure": structure("swing", BULL)}, {}, "inconsistent"),
    ],
)
def test_gate_returns_neutral_with_reason(snapshot_changes, input_changes, reason) -> None:  # type: ignore[no-untyped-def]
    ev = evaluate(make_snapshot(**snapshot_changes), **input_changes)
    if reason is None:  # no ATR: no plan possible -> still never a trade
        assert not ev.is_trade
        return
    assert ev.signal_class is SignalClass.NEUTRAL and ev.neutral_reason == NEUTRAL_TEXT[reason]
    assert ev.plan is None


def test_gate_extreme_volatility_and_missing_htf() -> None:
    hot = make_snapshot()
    hot = replace(hot, volatility=replace(must(hot.volatility), atr_percentile=99.5))
    assert evaluate(hot).neutral_reason == NEUTRAL_TEXT["volatility"]
    mtf = must(make_snapshot().multi_timeframe)
    no_htf = make_snapshot(
        multi_timeframe=replace(mtf, higher=(frame("15m", ready=False), frame("1h")))
    )
    assert evaluate(no_htf).neutral_reason == NEUTRAL_TEXT["no_htf"]


def test_no_trigger_means_no_opportunity() -> None:
    quiet = make_snapshot(
        internal_structure=structure("internal", BULL, (event(time=T - 3 * 300),), low=98.0)
    )
    ev = evaluate(quiet)
    assert ev.signal_class is SignalClass.NEUTRAL and ev.neutral_reason == "لا توجد فرصة واضحة"


# --- scoring --------------------------------------------------------------------------------
def test_default_scene_is_a_transparent_buy() -> None:
    ev = evaluate()
    assert ev.signal_class is SignalClass.BUY and ev.side is Side.LONG
    assert (
        ev.hypothesis is not None and must(ev.hypothesis).family is SetupFamily.TREND_CONTINUATION
    )
    names = [c.name for c in must(ev.hypothesis).components]
    assert names == [
        "htf",
        "structure",
        "liquidity",
        "location",
        "trend",
        "displacement",
        "volume",
        "candle",
        "momentum",
    ]
    assert 0 <= ev.score <= 100
    assert must(ev.hypothesis).positive and all(
        isinstance(r, str) for r in must(ev.hypothesis).positive
    )
    assert ev.strategy_version == strategy_version(DEFAULT_SIGNAL_CONFIG)


def test_bull_and_bear_are_independent_not_complements() -> None:
    ev = evaluate()
    assert ev.bull_score > 0 and ev.bear_score == 0.0  # no bearish trigger: no bear evidence
    assert ev.bull_score + ev.bear_score != 100


def test_normalization_excludes_unavailable_categories() -> None:
    out = Scored([Component("a", 1.0, 20, 20), Component("b", 0.5, 10, 5)], [], [], [])
    base, final = finalize(out)
    assert base == pytest.approx(83.33, abs=0.01) and final == pytest.approx(83.33, abs=0.01)
    one_h = make_snapshot(
        timeframe="1h", multi_timeframe=replace(must(make_snapshot().multi_timeframe), higher=())
    )
    ev = evaluate(one_h)
    assert ev.hypothesis is not None
    assert "htf" not in [
        c.name for c in must(ev.hypothesis).components
    ]  # no 4h: excluded, not zero


def test_trigger_cluster_cap_prevents_double_counting() -> None:
    ctx = Ctx(make_snapshot(), Side.LONG, bars(), 0.01, DEFAULT_SIGNAL_CONFIG)
    out = Scored([], [], [], [])
    trig = Trigger("x", T, "internal", "BOS", "bullish", 100.0, 5.0, 99.5)
    score_trigger_cluster(ctx, out, trig)
    assert sum(c.weight for c in out.components) == pytest.approx(
        DEFAULT_SIGNAL_CONFIG.weights.trigger_cluster_cap
    )
    assert sum(c.points for c in out.components) == pytest.approx(10.0)  # not 15


def test_neutral_when_weak_or_conflicted() -> None:
    weak = make_snapshot(
        multi_timeframe=replace(
            must(make_snapshot().multi_timeframe),
            higher=(frame("15m", "bearish", "downtrend"), frame("1h", "bearish", "downtrend")),
        ),
        trend=replace(must(make_snapshot().trend), score=-0.2),
    )
    ev = evaluate(weak)
    assert (
        ev.signal_class is SignalClass.NEUTRAL
        and ev.score < DEFAULT_SIGNAL_CONFIG.regular_threshold
    )
    # Conflicted: equal evidence both ways -> NEUTRAL even above threshold.
    lenient = SignalEngine(SignalConfig(regular_threshold=10, min_score_spread=200))
    ev2 = lenient.evaluate(make_input())
    assert (
        ev2.signal_class is SignalClass.NEUTRAL and ev2.neutral_reason == NEUTRAL_TEXT["conflicted"]
    )


def test_strong_class_only_when_enabled() -> None:
    assert DEFAULT_SIGNAL_CONFIG.strong_enabled is False  # validation did not support it
    eng = SignalEngine(SignalConfig(strong_enabled=True, strong_threshold=70))
    assert eng.evaluate(make_input()).signal_class is SignalClass.STRONG_BUY


# --- penalties --------------------------------------------------------------------------------
def _penalties(ev: SignalEvaluation) -> set[str]:
    return {p.code for p in must(ev.hypothesis).penalties}


def test_penalty_strong_htf_opposition() -> None:
    mtf = must(make_snapshot().multi_timeframe)
    snap = make_snapshot(
        multi_timeframe=replace(
            mtf, higher=(frame("15m"), frame("1h", "bearish", "strong_downtrend"))
        )
    )
    ev = evaluate(snap)
    assert "htf_strong_opposition" in _penalties(ev)
    assert must(ev.hypothesis).score < must(evaluate().hypothesis).score


def test_penalties_location_volatility_volume_sweep_zone() -> None:
    base = make_snapshot()
    snap = replace(
        base,
        premium_discount=replace(
            must(base.premium_discount), position=92.0, zone=PremiumDiscountZone.PREMIUM
        ),
        volatility=replace(must(base.volatility), regime=VolatilityRegime.EXTREME),
        internal_structure=structure("internal", BULL, (event(relvol=0.4),), low=98.0),
        liquidity=replace(
            must(base.liquidity), sweeps=(sweep(LiquiditySide.BUY_SIDE, 100.5, 100.9, bars_ago=2),)
        ),
        order_blocks=(order_block(ZoneType.BEARISH_OB, 101.0, 100.3),),
    )
    codes = _penalties(evaluate(snap))
    assert {
        "extreme_location",
        "extreme_volatility",
        "volume_contradiction",
        "adverse_sweep",
        "opposing_zone_ahead",
    } <= codes


# --- setup families ---------------------------------------------------------------------------
def test_trend_continuation_requires_aligned_swing() -> None:
    against = make_snapshot(swing_structure=structure("swing", BEAR, high=105.0))
    ev = evaluate(against)
    assert ev.signal_class is SignalClass.NEUTRAL
    assert "الهيكل الرئيسي غير متوافق" in (ev.neutral_reason or "")


def test_pullback_continuation_needs_value_and_uses_zone_entry() -> None:
    choch = event(kind="CHOCH")
    base = make_snapshot(
        internal_structure=structure("internal", BULL, (choch,), low=98.0, break_high=101.5),
        order_blocks=(order_block(ZoneType.BULLISH_OB, 99.6, 98.8),),
    )
    dipped = bars([97 + i * 0.1 for i in range(29)] + [100.0])
    ev = evaluate(base, recent_bars=dipped)
    assert (
        ev.hypothesis is not None
        and must(ev.hypothesis).family is SetupFamily.PULLBACK_CONTINUATION
    )
    assert ev.plan is not None and ev.plan.entry_model.value == "ZONE_ENTRY"
    assert ev.plan.entry_low == pytest.approx(99.6) and ev.plan.entry_high == pytest.approx(100.0)
    high = make_snapshot(
        internal_structure=structure("internal", BULL, (choch,), low=98.0),
        premium_discount=replace(must(base.premium_discount), equilibrium=90.0),
    )
    flat = bars([100.0] * 30)
    assert evaluate(high, recent_bars=flat).hypothesis is None  # pullback never reached value


def test_breakout_requires_displacement_volume_and_acceptance() -> None:
    swing_bos = event(layer="swing", level=99.0)
    ok = make_snapshot(
        swing_structure=structure("swing", BULL, (swing_bos,), low=95.0),
        internal_structure=structure("internal", BULL, low=98.0),
    )
    ev = evaluate(ok)
    assert (
        ev.hypothesis is not None
        and must(ev.hypothesis).family is SetupFamily.BREAKOUT_CONTINUATION
    )
    weak = replace(
        ok,
        swing_structure=structure(
            "swing", BULL, (event(layer="swing", displacement=30),), low=95.0
        ),
    )
    assert evaluate(weak).hypothesis is None
    rejected = replace(ok, candle=candle(close_location=0.2, patterns=()))
    assert evaluate(rejected).hypothesis is None  # immediately rejected breakout


def test_liquidity_reversal_needs_sweep_back_inside_and_intact_low() -> None:
    choch = event(kind="CHOCH")
    base = make_snapshot(
        swing_structure=structure("swing", BEAR, high=105.0, break_low=94.0),
        internal_structure=structure("internal", BULL, (choch,), low=98.0),
        liquidity=replace(
            must(make_snapshot().liquidity), sweeps=(sweep(LiquiditySide.SELL_SIDE, 98.5, 97.8),)
        ),
    )
    ev = evaluate(base, recent_bars=bars([99.0] * 30))
    assert (
        ev.hypothesis is not None and must(ev.hypothesis).family is SetupFamily.LIQUIDITY_REVERSAL
    )
    assert ev.plan is None or ev.plan.stop < 97.8  # stop below the sweep extreme
    undercut = bars([99.0] * 28 + [97.0, 99.0])  # a later low broke the sweep extreme
    assert all(
        h is None or h.family is not SetupFamily.LIQUIDITY_REVERSAL
        for h in (evaluate(base, recent_bars=undercut).hypothesis,)
    )
    no_sweep = replace(base, liquidity=make_snapshot().liquidity)
    assert evaluate(no_sweep).hypothesis is None


def test_bearish_mirror() -> None:
    bear_bos = event(direction=BEAR, level=100.5)
    snap = make_snapshot(
        swing_structure=structure("swing", BEAR, high=105.0, break_low=94.0),
        internal_structure=structure("internal", BEAR, (bear_bos,), high=102.0, break_low=98.5),
        trend=replace(
            must(make_snapshot().trend),
            direction=must(make_snapshot().trend).direction.__class__("bearish"),
            score=-0.7,
        ),
        regime=replace(
            must(make_snapshot().regime),
            directional=must(make_snapshot().regime).directional.__class__("downtrend"),
        ),
        multi_timeframe=replace(
            must(make_snapshot().multi_timeframe),
            higher=(frame("15m", "bearish", "downtrend"), frame("1h", "bearish", "downtrend")),
        ),
        momentum=replace(must(make_snapshot().momentum), rsi=40.0, rsi_slope=-1.0),
        candle=candle(direction="down", close_location=0.1),
        liquidity=replace(
            must(make_snapshot().liquidity),
            pools=(pool(96.0, LiquiditySide.SELL_SIDE),),
            nearest_buy_side=None,
            nearest_sell_side=96.0,
        ),
    )
    ev = evaluate(snap, recent_bars=bars([105 - i * 5 / 29 for i in range(30)]))
    assert ev.side is Side.SHORT and ev.signal_class is SignalClass.SELL
    assert ev.plan is not None and ev.plan.stop > ev.plan.preferred_entry
    assert ev.bull_score == 0.0


# --- developing ---------------------------------------------------------------------------------
def test_developing_signal_from_forming_break() -> None:
    dev = DevelopingFeatures(
        internal_breaks=(
            DevelopingBreak(StructureLayer.INTERNAL, StructureEventType.BOS, BULL, 99.5, 100.0),
        )
    )
    snap = make_snapshot(
        forming_time=T + 300,
        forming_candle=candle(),
        internal_structure=structure("internal", NEUTRAL, (), low=98.0),
        developing=dev,
    )
    ev = evaluate(snap, developing=True)
    assert ev.developing is True and ev.candle_time == T + 300
    assert ev.hypothesis is not None and must(ev.hypothesis).trigger.id.startswith("dev:")


def test_deterministic() -> None:
    a, b = evaluate(), evaluate()
    assert a == b
