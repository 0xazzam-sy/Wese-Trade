"""Replay/backtest: canonical engines, no lookahead, pass-1 == pass-2, metrics, calibration."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from itertools import pairwise

import pytest

from app.backtesting.metrics import compute
from app.backtesting.runner import ReplayResult, reclassify, replay, simulate
from app.market_data.models import Candle
from app.market_data.timeframes import Timeframe
from app.signal_engine.calibration import calibration_table, monotonic_score
from app.signal_engine.config import DEFAULT_SIGNAL_CONFIG, SignalConfig, strategy_version
from app.signal_engine.enums import ExitReason, Side
from app.signal_engine.models import Signal
from tests.analysis.helpers import load_fixture
from tests.signals.builders import must

# The fixture is too short for 15m/1h context readiness, so only that gate is relaxed here.
LENIENT = DEFAULT_SIGNAL_CONFIG.with_changes(
    regular_threshold=40.0,
    min_score_spread=0.0,
    min_risk_cost_multiple=1.0,
    require_htf_context=False,
)


def _aggregate(candles: list[Candle], tf: Timeframe) -> list[Candle]:
    out: list[Candle] = []
    bucket: list[Candle] = []
    per = tf.seconds // candles[0].timeframe.seconds
    for c in candles:
        start = tf.bucket_start_ms(c.open_ms)
        if bucket and tf.bucket_start_ms(bucket[0].open_ms) != start:
            bucket = []
        bucket.append(c)
        if len(bucket) == per:
            out.append(
                Candle(
                    c.symbol,
                    tf,
                    datetime.fromtimestamp(start / 1000, tz=UTC),
                    bucket[0].open,
                    max(b.high for b in bucket),
                    min(b.low for b in bucket),
                    bucket[-1].close,
                    sum((b.volume for b in bucket), Decimal(0)),
                    True,
                )
            )
            bucket = []
    return out


@pytest.fixture(scope="module")
def data() -> tuple[list[Candle], dict[Timeframe, list[Candle]], float]:
    candles, tick = load_fixture("okx_btcusdt_5m")
    ctx = {
        Timeframe.M15: _aggregate(candles, Timeframe.M15),
        Timeframe.H1: _aggregate(candles, Timeframe.H1),
    }
    return candles, ctx, tick


def _run(
    candles: list[Candle],
    ctx: dict[Timeframe, list[Candle]],
    tick: float,
    cfg: SignalConfig = LENIENT,
) -> ReplayResult:
    return replay("BTCUSDT", Timeframe.M5, candles, ctx, tick=tick, config=cfg)


def _frozen(s: Signal) -> tuple:  # type: ignore[type-arg]
    return (s.id, s.side, s.family, s.score, s.confirmed_time, s.plan)


def test_replay_produces_signals_with_valid_plans(data) -> None:  # type: ignore[no-untyped-def]
    candles, ctx, tick = data
    result = _run(candles, ctx, tick)
    assert result.triggers > 0 and result.signals, (
        "lenient config must produce signals on 700 real candles"
    )
    for s in result.signals:
        sign = s.side.sign
        prices = [s.plan.preferred_entry, *(t.price for t in s.plan.targets)]
        assert all(sign * (b - a) > 0 for a, b in pairwise(prices))
        assert sign * (s.plan.preferred_entry - s.plan.stop) > 0
        assert s.confirmed_time == s.trigger_time + 300


def test_pass2_simulation_equals_pass1(data) -> None:  # type: ignore[no-untyped-def]
    candles, ctx, tick = data
    result = _run(candles, ctx, tick)
    again = simulate(result, LENIENT)
    assert [(_frozen(s), s.state, s.net_r) for s in again] == [
        (_frozen(s), s.state, s.net_r) for s in result.signals
    ]


def test_no_lookahead_signals_independent_of_future(data) -> None:  # type: ignore[no-untyped-def]
    candles, ctx, tick = data
    full = _run(candles, ctx, tick)
    for n in (450, 550, 650):
        cut = candles[n].open_ms // 1000 + 300
        pivot = candles[n].close
        future = [
            replace(
                c,
                open=2 * pivot - c.open,
                high=2 * pivot - c.low,
                low=2 * pivot - c.high,
                close=2 * pivot - c.close,
            )
            for c in candles[n + 1 :]
        ]
        alt = _run(candles[: n + 1] + future, ctx, tick)
        known = [_frozen(s) for s in full.signals if s.confirmed_time <= cut]
        assert known == [_frozen(s) for s in alt.signals if s.confirmed_time <= cut]


def test_incremental_equals_fresh_replay(data) -> None:  # type: ignore[no-untyped-def]
    candles, ctx, tick = data
    full = _run(candles, ctx, tick)
    prefix = _run(candles[:600], ctx, tick)
    cut = candles[599].open_ms // 1000 + 300
    assert [_frozen(s) for s in prefix.signals] == [
        _frozen(s) for s in full.signals if s.confirmed_time <= cut
    ]


def _sig(r: float, score: float = 80.0, ambiguous: bool = False) -> Signal:
    from tests.signals.test_lifecycle import base_eval, with_plan

    ev = with_plan(base_eval())
    s = Signal(
        id=f"s{r}{score}",
        symbol="BTCUSDT",
        timeframe="5m",
        side=Side.LONG,
        signal_class=ev.signal_class,
        family=must(ev.hypothesis).family,
        score=score,
        trigger_id="t",
        trigger_time=0,
        confirmed_time=int(score * 100 + r * 10),
        plan=must(ev.plan),
        components=(),
        penalties=(),
        positive=(),
        negative=(),
        evidence={"entry_market": True},
        strategy_version="v",
        regime="uptrend",
    )
    s.entered_time, s.entry_price, s.exit_reason, s.ambiguous = 0, 100.0, ExitReason.STOP, ambiguous
    s.gross_r = s.net_r = r
    return s


def test_metrics_profit_factor_drawdown_streaks() -> None:
    stats = compute([_sig(2.0, 70), _sig(-1.0, 71), _sig(-1.0, 72), _sig(1.0, 73, ambiguous=True)])
    assert stats.entered == 4 and stats.wins == 2 and stats.ambiguous == 1
    assert stats.expectancy == pytest.approx(0.25)
    assert stats.profit_factor == pytest.approx(3.0 / 2.0)
    assert stats.max_drawdown_r == pytest.approx(2.0)
    assert (stats.max_consecutive_wins, stats.max_consecutive_losses) == (1, 2)


def test_calibration_buckets() -> None:
    rows = calibration_table([_sig(1.0, 72), _sig(-1.0, 78), _sig(2.0, 92), _sig(0.5, 100)])
    by = {r["bucket"]: r for r in rows}
    assert by["70-74"]["entered"] == 1 and by["75-79"]["expectancy"] == -1.0
    assert by["95-100"]["entered"] == 1
    assert monotonic_score(rows) is None  # too few samples to claim anything


def test_strategy_version_tracks_configuration() -> None:
    v = strategy_version(DEFAULT_SIGNAL_CONFIG)
    assert v == strategy_version(DEFAULT_SIGNAL_CONFIG)
    assert v != strategy_version(DEFAULT_SIGNAL_CONFIG.with_changes(regular_threshold=76.0))
    assert v.startswith("wese-trade-signal-4.0-")


def test_reclassify_tolerates_tick_rounded_floor_but_rejects_costly_plans(data) -> None:  # type: ignore[no-untyped-def]
    candles, ctx, tick = data
    result = _run(candles, ctx, tick)
    ev = next(e for _, e in result.evaluations if e.is_trade)
    plan = must(ev.plan)
    floor = LENIENT.min_risk_cost_multiple * LENIENT.round_trip_cost_rate() * plan.preferred_entry
    # A stop widened to the floor, then compared against a half-tick-rounded entry.
    rounded = replace(ev, plan=replace(plan, risk=floor * (1 - 3e-5)))
    assert reclassify(rounded, LENIENT).signal_class is ev.signal_class
    costly = replace(ev, plan=replace(plan, risk=floor * 0.9))
    assert reclassify(costly, LENIENT).signal_class.value == "NEUTRAL"
