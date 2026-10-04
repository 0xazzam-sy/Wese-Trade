"""SignalTracker: confirmation freeze, cooldown, dedupe, fills, exits, ambiguity, costs."""

from __future__ import annotations

from dataclasses import replace

import pytest

from app.analysis.series import Bar
from app.signal_engine.config import DEFAULT_SIGNAL_CONFIG, SignalConfig
from app.signal_engine.engine import SignalEngine
from app.signal_engine.enums import EntryModel, ExitReason, Side, SignalClass, SignalState
from app.signal_engine.lifecycle import SignalTracker, compute_r, signal_id
from app.signal_engine.models import SignalEvaluation, Target, TradePlan
from tests.signals.builders import STEP, T, make_input, must

FREE = DEFAULT_SIGNAL_CONFIG.with_changes(fee_rate=0.0, maker_fee_rate=0.0, slippage_rate=0.0)


def base_eval() -> SignalEvaluation:
    ev = SignalEngine().evaluate(make_input())
    assert ev.is_trade
    return ev


def with_plan(
    ev: SignalEvaluation,
    *,
    model: EntryModel = EntryModel.MARKET,
    entry: float = 100.0,
    stop: float = 98.0,
    tps: tuple[float, float, float] = (102.0, 104.0, 106.0),
) -> SignalEvaluation:
    risk = abs(entry - stop)
    t1, t2, t3 = (Target(p, round(abs(p - entry) / risk, 2), "test") for p in tps)
    low, high = (min(entry, 100.0), max(entry, 100.0))
    plan = TradePlan(model, low, high, entry, stop, stop, "test", risk, risk, (t1, t2, t3))
    return replace(ev, plan=plan)


def retrigger(ev: SignalEvaluation, trigger_id: str) -> SignalEvaluation:
    hyp = must(ev.hypothesis)
    return replace(ev, hypothesis=replace(hyp, trigger=replace(hyp.trigger, id=trigger_id)))


def bar(i: int, o: float, h: float, lo: float, c: float) -> Bar:
    t = T + i * STEP
    return Bar(i, t, t + STEP, o, h, lo, c, 10.0)


def tracker(cfg: SignalConfig = FREE) -> tuple[SignalTracker, list[tuple[str, str]]]:
    events: list[tuple[str, str]] = []
    tr = SignalTracker(
        "BTCUSDT", "5m", cfg, step_seconds=STEP, sink=lambda k, s: events.append((k, s.state.value))
    )
    return tr, events


def test_confirmation_freezes_and_market_entry_fills_at_close() -> None:
    tr, events = tracker()
    s = tr.on_evaluation(with_plan(base_eval()), bar(0, 99, 100.5, 98.9, 100))
    assert s is not None and s.entry_price == 100.0
    assert s.state.value == "active"
    assert s.confirmed_time == T + STEP and events == [("confirmed", "active")]
    frozen = (s.plan, s.score, s.family, s.trigger_id)
    tr.on_bar(bar(1, 100, 102.5, 99.5, 102.2))
    assert (s.plan, s.score, s.family, s.trigger_id) == frozen  # lifecycle never rewrites
    assert s.state is SignalState.TP1_HIT and s.targets_hit == 1


def test_targets_and_r_accounting() -> None:
    tr, _ = tracker()
    s = tr.on_evaluation(with_plan(base_eval()), bar(0, 99, 100.5, 98.9, 100))
    tr.on_bar(bar(1, 100, 102.5, 99.5, 102.2))
    tr.on_bar(bar(2, 102, 106.5, 101.5, 106))
    assert s is not None and s.state is SignalState.TP3_HIT and s.exit_reason is ExitReason.TP3
    assert s.gross_r == pytest.approx((1 + 2 + 3) / 3)
    assert tr.active is None


def test_stop_loss() -> None:
    tr, events = tracker()
    s = tr.on_evaluation(with_plan(base_eval()), bar(0, 99, 100.5, 98.9, 100))
    tr.on_bar(bar(1, 99.5, 99.8, 97.5, 97.8))
    assert s is not None and s.state is SignalState.STOPPED and s.gross_r == pytest.approx(-1.0)
    assert events[-1] == ("closed", "stopped")


def test_same_candle_ambiguity_is_conservative() -> None:
    tr, _ = tracker()
    s = tr.on_evaluation(with_plan(base_eval()), bar(0, 99, 100.5, 98.9, 100))
    tr.on_bar(bar(1, 100, 102.5, 97.5, 100))  # both TP1 and the stop inside one candle
    assert s is not None and s.ambiguous and s.state is SignalState.STOPPED
    assert s.gross_r == pytest.approx(-1.0)  # never the favorable assumption


def test_gap_through_stop_exits_at_open() -> None:
    tr, _ = tracker()
    s = tr.on_evaluation(with_plan(base_eval()), bar(0, 99, 100.5, 98.9, 100))
    tr.on_bar(bar(1, 97.0, 97.5, 96.5, 97.2))
    assert s is not None and s.gross_r == pytest.approx(-1.5)


def test_zone_entry_fill_expiry_and_invalidation() -> None:
    ev = with_plan(base_eval(), model=EntryModel.ZONE, entry=99.5, stop=98.0)
    tr, _ = tracker()
    s = tr.on_evaluation(ev, bar(0, 99, 100.5, 98.9, 100))
    assert s is not None and s.state is SignalState.CONFIRMED and not s.entered
    tr.on_bar(bar(1, 100, 103, 99.4, 102))  # fills at 99.5; TP on the fill candle NOT credited
    assert s.entered and s.entry_price == 99.5 and s.targets_hit == 0
    tr2, _ = tracker(FREE.with_changes(entry_expiry_bars=2))
    s2 = tr2.on_evaluation(ev, bar(0, 99, 100.5, 98.9, 100))
    tr2.on_bar(bar(1, 100, 101, 99.8, 100.5))
    tr2.on_bar(bar(2, 100.5, 101, 99.9, 100.6))
    assert s2 is not None and s2.state is SignalState.EXPIRED and s2.net_r is None
    tr3, _ = tracker()
    s3 = tr3.on_evaluation(
        replace(ev, plan=replace(must(ev.plan), preferred_entry=97.0, invalidation=98.0)),
        bar(0, 99, 100.5, 98.9, 100),
    )
    tr3.on_bar(bar(1, 99.5, 99.6, 97.6, 97.7))  # closes below invalidation before reaching 97
    assert s3 is not None and s3.state is SignalState.INVALIDATED


def test_time_stop() -> None:
    tr, _ = tracker(FREE.with_changes(max_hold_bars=3))
    s = tr.on_evaluation(with_plan(base_eval()), bar(0, 99, 100.5, 98.9, 100))
    for i in range(1, 4):
        tr.on_bar(bar(i, 100, 100.5, 99.5, 100.3))
    assert s is not None and s.state is SignalState.CLOSED and s.exit_reason is ExitReason.TIME
    assert s.gross_r == pytest.approx(0.15)


def test_cooldown_dedupe_and_active_conflicts() -> None:
    ev = with_plan(base_eval())
    tr, _ = tracker()
    first = tr.on_evaluation(ev, bar(0, 99, 100.5, 98.9, 100))
    assert first is not None
    assert tr.on_evaluation(ev, bar(1, 100, 100.5, 99.5, 100)) is None  # same trigger: duplicate
    assert tr.suppressed["duplicate"] == 1
    other = retrigger(ev, "other")
    assert tr.on_evaluation(other, bar(2, 100, 100.5, 99.5, 100)) is None
    assert tr.suppressed["cooldown"] == 1
    tr.remember({signal_id("BTCUSDT", "5m", "TREND_CONTINUATION", "long", "persisted")})
    persisted = retrigger(ev, "persisted")
    assert (
        tr.on_evaluation(persisted, bar(20, 100, 100.5, 99.5, 100)) is None
    )  # seen before restart


def test_opposite_strong_signal_overrides_active() -> None:
    ev = with_plan(base_eval())
    tr, _ = tracker()
    first = tr.on_evaluation(ev, bar(0, 99, 100.5, 98.9, 100))
    flipped = retrigger(ev, "s")
    short = replace(
        flipped,
        side=Side.SHORT,
        signal_class=SignalClass.SELL,
        hypothesis=replace(must(flipped.hypothesis), side=Side.SHORT),
        plan=with_plan(ev, entry=100.0, stop=102.0, tps=(98.0, 96.0, 94.0)).plan,
    )
    assert tr.on_evaluation(short, bar(1, 100, 100.4, 99.6, 100)) is None  # regular: suppressed
    strong = replace(short, signal_class=SignalClass.STRONG_SELL)
    second = tr.on_evaluation(strong, bar(2, 100, 100.4, 99.6, 100))
    assert second is not None and first is not None
    assert first.state is SignalState.CLOSED and first.exit_reason is ExitReason.OPPOSITE


def test_developing_never_confirms() -> None:
    tr, _ = tracker()
    dev = replace(with_plan(base_eval()), developing=True)
    assert tr.on_evaluation(dev, bar(0, 99, 100.5, 98.9, 100)) is None
    assert tr.active is None


def test_fees_and_slippage_reduce_net_r() -> None:
    tr, _ = tracker(DEFAULT_SIGNAL_CONFIG)
    s = tr.on_evaluation(with_plan(base_eval()), bar(0, 99, 100.5, 98.9, 100))
    tr.on_bar(bar(1, 99.5, 99.8, 97.5, 97.8))
    assert s is not None and s.gross_r == pytest.approx(-1.0)
    cfg = DEFAULT_SIGNAL_CONFIG
    expected_cost = (
        cfg.fee_rate * 100 + cfg.slippage_rate * 100 + cfg.fee_rate * 98 + cfg.slippage_rate * 98
    ) / 2
    assert s.net_r == pytest.approx(-1.0 - expected_cost, abs=1e-3)
    compute_r(s, FREE)
    assert s.net_r == pytest.approx(s.gross_r)


def test_break_even_option() -> None:
    tr, _ = tracker(FREE.with_changes(move_stop_to_entry_after_tp1=True))
    s = tr.on_evaluation(with_plan(base_eval()), bar(0, 99, 100.5, 98.9, 100))
    tr.on_bar(bar(1, 100, 102.5, 100.2, 102.0))
    tr.on_bar(bar(2, 101, 101.2, 99.8, 99.9))
    assert s is not None and s.state is SignalState.STOPPED
    assert s.gross_r == pytest.approx(1 / 3, abs=1e-3)  # TP1 third + two thirds at break-even
