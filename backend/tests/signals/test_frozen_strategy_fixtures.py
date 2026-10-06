"""The FROZEN forward strategy really produces BUY, SELL and NEUTRAL (real OKX candles).

Fixtures: ETH-USDT-SWAP 15m (+30m/1h context) from the Phase 4.1 research store, around
two signals the research simulator recorded for `wese-trade-research-4.1-c590e82e3a`.
Nothing is forced or tuned: the exact frozen candidate and default config are replayed
candle by candle through the live evaluator, and must reproduce those signals exactly.
"""

from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from app.analysis.engine import MarketAnalyzer
from app.forward_test.candidate import candidate, forward_version, frozen_config
from app.forward_test.evaluate import LiveContext, evaluate_candle
from app.market_data.models import Candle
from app.market_data.timeframes import Timeframe
from app.signal_engine.enums import EntryModel, SetupFamily, Side, SignalClass
from app.signal_engine.models import SignalEvaluation

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
FROZEN = "wese-trade-forward-4.2-a03e20f1d4"
CTX = (Timeframe.M30, Timeframe.H1)


def _load(name: str) -> tuple[dict[Timeframe, list[Candle]], float, int]:
    raw = json.loads(gzip.decompress((FIXTURES / f"{name}.json.gz").read_bytes()))
    frames = {
        Timeframe(tf): [
            Candle(
                symbol=raw["symbol"],
                timeframe=Timeframe(tf),
                open_time=datetime.fromtimestamp(r[0] / 1000, tz=UTC),
                open=Decimal(r[1]),
                high=Decimal(r[2]),
                low=Decimal(r[3]),
                close=Decimal(r[4]),
                volume=Decimal(r[5]),
                is_closed=True,
            )
            for r in rows
        ]
        for tf, rows in raw["frames"].items()
    }
    return frames, float(raw["tick_size"]), int(raw["trigger_time"])


def _replay(name: str) -> tuple[dict[int, SignalEvaluation], int]:
    frames, tick, trigger = _load(name)
    v = candidate()
    base = MarketAnalyzer("ETHUSDT", Timeframe.M15, tick_size=tick)
    ctx = {tf: MarketAnalyzer("ETHUSDT", tf, tick_size=tick) for tf in CTX}
    pos = dict.fromkeys(CTX, 0)
    out: dict[int, SignalEvaluation] = {}
    for candle in frames[Timeframe.M15]:
        close_ms = candle.open_ms + Timeframe.M15.milliseconds
        for tf in CTX:  # context candles closed at or before this close only (no lookahead)
            series = frames[tf]
            while pos[tf] < len(series) and series[pos[tf]].open_ms + tf.milliseconds <= close_ms:
                ctx[tf].update(series[pos[tf]])
                pos[tf] += 1
        base.update(candle)
        out[base.series.last.time] = evaluate_candle(
            v,
            base,
            [ctx[tf].frame() for tf in CTX],
            LiveContext(market_stale=False, symbol_active=True),
            strategy_version=FROZEN,
        )
    return out, trigger


def test_strategy_hash_is_still_frozen() -> None:
    assert forward_version(frozen_config()) == FROZEN


@pytest.mark.parametrize(
    ("name", "cls", "side", "score", "entry", "stop", "targets"),
    [
        (
            "frozen_buy",
            SignalClass.BUY,
            Side.LONG,
            81.15,
            2485.14,
            2467.73,
            (2508.38, 2518.31, 2558.56),
        ),
        (
            "frozen_sell",
            SignalClass.SELL,
            Side.SHORT,
            79.2,
            1876.0,
            1889.13,
            (1857.96, 1848.16, 1835.03),
        ),
    ],
)
def test_real_buy_and_sell(
    name: str,
    cls: SignalClass,
    side: Side,
    score: float,
    entry: float,
    stop: float,
    targets: tuple[float, float, float],
) -> None:
    evaluations, trigger = _replay(name)
    ev = evaluations[trigger]
    assert ev.signal_class is cls  # never STRONG_*: disabled
    assert ev.side is side
    assert ev.strategy_version == FROZEN
    assert ev.score == pytest.approx(score, abs=0.01)
    assert ev.hypothesis is not None
    assert ev.hypothesis.family is SetupFamily.TREND_CONTINUATION
    plan = ev.plan
    assert plan is not None
    assert plan.entry_model is EntryModel.ZONE  # retrace entry
    assert plan.preferred_entry == pytest.approx(entry)
    assert plan.stop == pytest.approx(stop)
    assert tuple(t.price for t in plan.targets) == pytest.approx(targets)
    risk = abs(entry - stop)
    assert [t.rr for t in plan.targets] == pytest.approx(
        [abs(t - entry) / risk for t in targets], rel=0.02
    )
    assert ev.hypothesis.positive  # reasons are shown to the user
    # every other candle in the window is NEUTRAL (the default), with a reason
    others = [e for t, e in evaluations.items() if t != trigger]
    assert all(e.signal_class is SignalClass.NEUTRAL for e in others[-6:])
    neutral = [e for e in others if e.signal_class is SignalClass.NEUTRAL]
    assert len(neutral) > 0.95 * len(others)
    assert all(e.neutral_reason for e in neutral)
    assert not any(e.signal_class.value.startswith("STRONG") for e in evaluations.values())


def test_stale_feed_turns_the_same_candle_neutral() -> None:
    frames, tick, trigger = _load("frozen_sell")
    v = candidate()
    base = MarketAnalyzer("ETHUSDT", Timeframe.M15, tick_size=tick)
    ctx = {tf: MarketAnalyzer("ETHUSDT", tf, tick_size=tick) for tf in CTX}
    pos = dict.fromkeys(CTX, 0)
    for candle in frames[Timeframe.M15]:
        close_ms = candle.open_ms + Timeframe.M15.milliseconds
        for tf in CTX:
            series = frames[tf]
            while pos[tf] < len(series) and series[pos[tf]].open_ms + tf.milliseconds <= close_ms:
                ctx[tf].update(series[pos[tf]])
                pos[tf] += 1
        base.update(candle)
        if base.series.last.time == trigger:
            break
    frames_ctx = [ctx[tf].frame() for tf in CTX]
    stale = evaluate_candle(
        v,
        base,
        frames_ctx,
        LiveContext(market_stale=True, symbol_active=True),
        strategy_version=FROZEN,
    )
    inactive = evaluate_candle(
        v,
        base,
        frames_ctx,
        LiveContext(market_stale=False, symbol_active=False),
        strategy_version=FROZEN,
    )
    assert stale.signal_class is SignalClass.NEUTRAL and stale.plan is None
    assert inactive.signal_class is SignalClass.NEUTRAL and inactive.plan is None


def test_ui_fixtures_match_engine() -> None:
    """The chart-marker fixture used by the frontend tests/E2E is exactly what the frozen
    engine produces (regenerate with `python -m tests.signals.ui_fixtures`)."""
    from tests.signals.ui_fixtures import OUTPUT, render

    assert OUTPUT.read_text(encoding="utf-8") == render()
    data = json.loads(render())
    buy, sell = data["buy"]["signal_at_confirmation"], data["sell"]["signal_at_confirmation"]
    assert (buy["signal_class"], buy["side"], buy["family"]) == (
        "BUY",
        "long",
        "TREND_CONTINUATION",
    )
    assert buy["trigger_time"] == int(datetime(2026, 9, 18, 5, 0, tzinfo=UTC).timestamp())
    assert buy["score"] == pytest.approx(81.15, abs=0.01)
    assert (sell["signal_class"], sell["side"]) == ("SELL", "short")
    assert sell["trigger_time"] == int(datetime(2026, 7, 31, 12, 0, tzinfo=UTC).timestamp())
    assert sell["score"] == pytest.approx(79.2, abs=0.01)
    assert all(s["strategy_version"] == FROZEN for k in ("buy", "sell") for s in data[k]["signals"])
