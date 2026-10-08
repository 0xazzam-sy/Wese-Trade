"""Execution engine (1m / 5m / 10m entry timing for an active Strategy 4.2 parent)."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from app.execution import engine
from app.execution.models import (
    Decision,
    ExecState,
    ExecutionSignal,
    Features,
    Level,
    Micro,
    ParentSetup,
)

VERSION = "wese-trade-forward-4.2-a03e20f1d4"


def parent(side: int = 1, tf: str = "15m", **kw: Any) -> ParentSetup:
    base: dict[str, Any]
    if side == 1:
        base = dict(entry_low=99.0, entry_high=100.0, entry=99.5, stop=98.0, invalidation=98.0,
                    targets=(102.0, 103.5, 105.0))  # fmt: skip
    else:
        base = dict(entry_low=100.0, entry_high=101.0, entry=100.5, stop=102.0, invalidation=102.0,
                    targets=(98.0, 96.5, 95.0))  # fmt: skip
    base = {"state": "confirmed", **base, **kw}
    return ParentSetup(
        signal_id=f"sig-{tf}-{side}", strategy="Wese Trade Forward 4.2", strategy_version=VERSION,
        symbol="BTCUSDT", timeframe=tf, side=side, family="TREND_CONTINUATION", score=80.0,
        confirmed_time=1_000, **base,
    )  # fmt: skip


def bullish_features(**kw: Any) -> Features:
    """A 1m candle in the parent long zone: EMA reclaim, internal BOS, support reaction."""
    f = Features(
        index=500, time=10_000, close_time=10_060, open=99.30, high=99.90, low=99.20, close=99.85,
        prev_close=99.30, atr=0.4, ema20=99.6, ema50=99.4, ema200=99.0, ema20_prev=99.55,
        ema_stack="bullish", regime="uptrend", direction="bullish", rsi=56.0, rsi_slope=6.0,
        structure_events=((500, "BOS", "bullish"),), sweeps=((498, "sell_side", 99.1),),
        supports=(Level(99.25, 8.5, "strong", "support"),),
        resistances=(Level(101.5, 4.0, "medium", "resistance"),),
        swing_low=99.1, swing_high=100.4, tick=0.01,
    )  # fmt: skip
    return replace(f, **kw)


def bearish_features(**kw: Any) -> Features:
    f = Features(
        index=500, time=10_000, close_time=10_060, open=100.70, high=100.80, low=100.10,
        close=100.15, prev_close=100.70, atr=0.4, ema20=100.4, ema50=100.6, ema200=101.0,
        ema20_prev=100.45, ema_stack="bearish", regime="downtrend", direction="bearish", rsi=44.0,
        rsi_slope=-6.0, structure_events=((500, "CHOCH", "bearish"),), sweeps=(),
        supports=(Level(98.5, 4.0, "medium", "support"),),
        resistances=(Level(100.75, 8.5, "strong", "resistance"),),
        swing_low=99.6, swing_high=100.9, tick=0.01,
    )  # fmt: skip
    return replace(f, **kw)


# --- parent selection ----------------------------------------------------------------------
def test_parent_mapping_and_conflict() -> None:
    p15, p1h = parent(tf="15m"), parent(tf="1h")
    assert engine.select_parent("1m", [p1h]) == (None, False)  # 1h is not a 1m parent
    assert engine.select_parent("10m", [p1h]) == (p1h, False)
    assert engine.select_parent("5m", [p15, parent(-1, "30m")]) == (None, True)
    closed = replace(p15, state="stopped")
    assert engine.select_parent("1m", [closed]) == (None, False)


def test_no_parent_is_no_setup() -> None:
    ev = engine.evaluate("BTCUSDT", "1m", bullish_features(), None)
    assert ev.decision is Decision.NO_SETUP and ev.plan is None
    assert ev.headline == "لا توجد فرصة تداول مؤكدة حالياً."


def test_conflict_is_no_setup_with_reason() -> None:
    ev = engine.evaluate("BTCUSDT", "5m", bullish_features(), None, conflict=True)
    assert ev.decision is Decision.NO_SETUP and "تعارض" in ev.headline


# --- BUY / SELL confirmation ------------------------------------------------------------------
def test_15m_buy_parent_confirms_1m_buy() -> None:
    ev = engine.evaluate("BTCUSDT", "1m", bullish_features(), parent())
    assert ev.decision is Decision.BUY
    assert ev.score >= engine.CONFIRM_SCORE
    assert ev.plan is not None and ev.plan.entry == pytest.approx(99.85)
    assert ev.plan.targets == (102.0, 103.5, 105.0)  # parent targets kept
    assert ev.plan.rr[0] >= 1.0
    assert ev.reasons[0].startswith("اتجاه 15m صاعد")
    sig = engine.confirm(ev, bullish_features())
    assert sig is not None and sig.state is ExecState.READY
    assert sig.parent.strategy_version == VERSION and sig.parent.timeframe == "15m"
    assert sig.valid_until == 10_060 + 60


def test_15m_sell_parent_confirms_5m_sell() -> None:
    ev = engine.evaluate("BTCUSDT", "5m", bearish_features(), parent(-1))
    assert ev.decision is Decision.SELL
    assert ev.plan is not None and ev.plan.side == -1 and ev.plan.stop > ev.plan.entry


def test_30m_parent_confirms_10m_and_valid_until_is_half_candle() -> None:
    ev = engine.evaluate("BTCUSDT", "10m", bullish_features(), parent(tf="30m"))
    assert ev.decision is Decision.BUY
    sig = engine.confirm(ev, bullish_features())
    assert sig is not None and sig.valid_until == 10_060 + 300


def test_never_countertrend() -> None:
    """A bearish 1m candle cannot produce SELL under a bullish parent."""
    ev = engine.evaluate("BTCUSDT", "1m", bearish_features(), parent(1))
    assert ev.decision in (Decision.WAIT, Decision.NO_SETUP, Decision.ENTRY_MISSED)
    assert ev.side == 1


# --- WAIT / ENTRY MISSED --------------------------------------------------------------------------
def test_wait_without_trigger() -> None:
    quiet = bullish_features(
        structure_events=(), sweeps=(), ema20_prev=99.5, prev_close=99.7, supports=(),
        open=99.80, close=99.85, rsi=60.0, rsi_slope=1.0,
    )  # fmt: skip
    ev = engine.evaluate("BTCUSDT", "1m", quiet, parent())
    assert ev.decision is Decision.WAIT
    assert ev.headline == "الصفقة صاعدة لكن توقيت الدخول غير مناسب بعد."
    assert "لا توجد شمعة تأكيد على هذا الفريم بعد" in ev.cautions
    assert ev.plan is not None and ev.plan.entry == 99.5  # the zone entry while waiting


def test_extended_price_waits_for_retest() -> None:
    f = bullish_features(close=100.2, high=100.25, open=100.0, low=99.95)  # 0.47R beyond entry
    ev = engine.evaluate("BTCUSDT", "1m", f, parent())
    assert ev.decision is Decision.WAIT
    assert ev.headline == "الاتجاه الشرائي مؤكد، بانتظار إعادة اختبار منطقة الدخول."


def test_entry_missed_when_price_ran() -> None:
    f = bullish_features(close=101.2, high=101.3, open=100.9, low=100.85)
    ev = engine.evaluate("BTCUSDT", "1m", f, parent())
    assert ev.decision is Decision.ENTRY_MISSED
    assert ev.headline == "فاتت منطقة الدخول — لا تلاحق السعر."


def test_entry_missed_after_parent_tp1() -> None:
    ev = engine.evaluate("BTCUSDT", "1m", bullish_features(), parent(state="tp1_hit"))
    assert ev.decision is Decision.ENTRY_MISSED


def test_beyond_invalidation_is_no_setup() -> None:
    f = bullish_features(close=97.9, low=97.8, high=98.2, open=98.1)
    assert engine.evaluate("BTCUSDT", "1m", f, parent()).decision is Decision.NO_SETUP


# --- microstructure -----------------------------------------------------------------------------
def test_stale_microstructure_blocks_new_confirmation() -> None:
    stale = Micro(status="stale", book_age_s=60.0)
    ev = engine.evaluate("BTCUSDT", "1m", bullish_features(), parent(), micro=stale)
    assert ev.decision is Decision.WAIT
    assert "بيانات السوق اللحظية متأخرة — لا تأكيد جديد" in ev.cautions


def test_unavailable_microstructure_falls_back_to_structure() -> None:
    ev = engine.evaluate(
        "BTCUSDT", "1m", bullish_features(), parent(), micro=Micro(status="unavailable")
    )
    assert ev.decision is Decision.BUY


def test_abnormal_spread_reduces_score() -> None:
    ok = engine.evaluate("BTCUSDT", "1m", bullish_features(), parent())
    wide = Micro(status="ok", spread_bp=12.0, spread_normal_bp=2.0)
    ev = engine.evaluate("BTCUSDT", "1m", bullish_features(), parent(), micro=wide)
    assert ev.score == pytest.approx(ok.score - 10, abs=0.2)


# --- plan rules -----------------------------------------------------------------------------------
def test_stop_starts_from_parent_and_never_inside_noise() -> None:
    # swing low just below price: too tight (inside the noise) -> parent stop kept
    plan = engine.build_plan(parent(), 99.85, bullish_features(swing_low=99.7))
    assert plan.stop == 98.0 and plan.stop_source == "parent"
    # a structural swing far enough from entry and tighter than the parent -> refined
    plan = engine.build_plan(parent(), 99.85, bullish_features(swing_low=98.9, atr=0.3))
    assert plan.stop_source == "execution_structure"
    assert 98.0 < plan.stop < 98.9 and 99.85 - plan.stop >= 1.5 * 0.3


def test_score_band() -> None:
    assert [engine.score_band(x) for x in (20, 45, 65, 80, 90)] == [
        "poor", "weak", "acceptable", "strong", "very_strong",
    ]  # fmt: skip


def state(s: ExecutionSignal) -> ExecState:
    return s.state


# --- lifecycle -----------------------------------------------------------------------------
def _signal(side: int = 1) -> ExecutionSignal:
    f = bullish_features() if side == 1 else bearish_features()
    ev = engine.evaluate("BTCUSDT", "1m", f, parent(side))
    s = engine.confirm(ev, f)
    assert s is not None
    return s


def test_lifecycle_tp1_tp2_tp3() -> None:
    s = _signal()
    assert engine.advance(s, 99.95, 99.80, 10_120)
    assert state(s) is ExecState.ACTIVE
    engine.advance(s, 102.1, 100.0, 10_180)
    assert state(s) is ExecState.TP1_HIT
    engine.advance(s, 103.6, 101.9, 10_240)
    assert state(s) is ExecState.TP2_HIT
    engine.advance(s, 105.2, 103.0, 10_300)
    assert state(s) is ExecState.TP3_HIT and not s.is_open
    states = [h[1] for h in s.history]
    assert states == ["ready", "active", "tp1_hit", "tp2_hit", "tp3_hit"]


def test_lifecycle_stopped_stop_first() -> None:
    s = _signal()
    engine.advance(s, 99.95, 99.80, 10_120)
    engine.advance(s, 102.5, 97.5, 10_180)  # both: stop first
    assert state(s) is ExecState.STOPPED


def test_lifecycle_entry_missed_and_expired() -> None:
    s = _signal()
    engine.advance(s, 100.6, 100.0, 10_120)  # never back to entry
    assert state(s) is ExecState.READY
    engine.advance(s, 100.9, 100.2, 10_180)  # window passed
    assert state(s) is ExecState.ENTRY_MISSED
    s2 = _signal()
    engine.advance(s2, 100.6, 100.0, 10_120, parent_state="invalidated")
    assert state(s2) is ExecState.EXPIRED


def test_lifecycle_short_targets() -> None:
    s = _signal(-1)
    engine.advance(s, 100.3, 100.0, 10_120)
    assert state(s) is ExecState.ACTIVE
    engine.advance(s, 99.0, 97.9, 10_180)
    assert state(s) is ExecState.TP1_HIT


def test_existing_signal_is_shown_not_reissued() -> None:
    s = _signal()
    ev = engine.evaluate("BTCUSDT", "1m", bullish_features(index=501), parent(), signal=s)
    assert ev.decision is Decision.BUY and ev.trigger == s.trigger
    s.state = ExecState.ENTRY_MISSED
    ev = engine.evaluate("BTCUSDT", "1m", bullish_features(index=501), parent(), signal=s)
    assert ev.decision is Decision.ENTRY_MISSED
