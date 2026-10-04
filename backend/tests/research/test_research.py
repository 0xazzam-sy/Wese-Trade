"""Phase 4.1 research infrastructure: store, walk-forward, variants, costs, LTF, versioning.

Synthetic / fixture data only (unit tests). Real research results come from real OKX data.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from itertools import pairwise
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.analysis.series import Bar
from app.backtesting.runner import replay
from app.market_data.models import Candle
from app.market_data.timeframes import Timeframe
from app.research.collect import ALL_FAMILIES, SeriesResearch, TriggerRecord, collect
from app.research.ltf import ltf_entries
from app.research.simulate import (
    BASELINE,
    BASELINE_VERSION,
    COSTS,
    ScoreModel,
    Variant,
    retrace_plan,
    run,
)
from app.research.store import ResearchStore
from app.research.studies import calibration
from app.research.universe import UniverseMember, eligible, rank
from app.research.walkforward import (
    DAY,
    MIN_VALIDATION_TRADES,
    assess,
    development,
    make_windows,
    stats,
    validation,
    window_of,
)
from app.signal_engine.config import DEFAULT_SIGNAL_CONFIG
from app.signal_engine.enums import EntryModel, ExitReason, Side, SignalState
from app.signal_engine.models import Component, Hypothesis, Penalty, Signal, TradePlan, Trigger
from tests.analysis.helpers import load_fixture
from tests.signals.test_backtest import LENIENT, _aggregate

LENIENT_VARIANT = Variant("lenient", threshold=40.0, spread=0.0)


def _candle(tf: Timeframe, minute: int, price: str = "100", closed: bool = True) -> Candle:
    return Candle(
        symbol="BTCUSDT",
        timeframe=tf,
        open_time=datetime.fromtimestamp(1_700_000_000 + minute * 60, tz=UTC),
        open=Decimal(price),
        high=Decimal(price) + 1,
        low=Decimal(price) - 1,
        close=Decimal(price),
        volume=Decimal("5"),
        is_closed=closed,
    )


@pytest.fixture(scope="module")
def research() -> tuple[SeriesResearch, list[Signal]]:
    candles, tick = load_fixture("okx_btcusdt_5m")
    ctx = {
        Timeframe.M15: _aggregate(candles, Timeframe.M15),
        Timeframe.H1: _aggregate(candles, Timeframe.H1),
    }
    series = collect("BTCUSDT", Timeframe.M5, candles, ctx, tick=tick, config=LENIENT)
    canonical = replay("BTCUSDT", Timeframe.M5, candles, ctx, tick=tick, config=LENIENT)
    return series, canonical.signals


# --- historical store -----------------------------------------------------------------------
def test_store_dedupes_strictly_and_counts_conflicts(tmp_path: Path) -> None:
    store = ResearchStore(tmp_path / "s.sqlite")
    tf = Timeframe.M1
    first = store.insert([_candle(tf, 0), _candle(tf, 1), _candle(tf, 2, closed=False)], "test")
    assert (first.inserted, first.duplicates, first.conflicts) == (2, 0, 0)  # open candle skipped
    again = store.insert([_candle(tf, 1), _candle(tf, 1, price="105")], "test")
    assert (again.inserted, again.duplicates, again.conflicts) == (0, 2, 1)
    loaded = store.load("BTCUSDT", tf)
    assert [k.open_ms for k in loaded] == sorted(k.open_ms for k in loaded)
    assert loaded[1].close == Decimal("100")  # the stored value is never overwritten
    store.insert([_candle(tf, 5)], "test")
    cov = store.coverage("BTCUSDT", tf)
    assert (cov.candles, cov.gaps) == (3, 1)
    assert store.insert_funding("BTCUSDT", [(1, "0.0001"), (1, "0.0001")], "t") == 1
    run_id = store.save_run(
        "r", baseline_version="b", analysis_version="a", metadata={"x": 1}, results={"y": 2}
    )
    assert store.run(run_id)["results"] == {"y": 2}  # type: ignore[index]
    store.close()


def test_store_aggregates_10m_from_5m(tmp_path: Path) -> None:
    store = ResearchStore(tmp_path / "s.sqlite")
    store.insert([replace(_candle(Timeframe.M5, 0), timeframe=Timeframe.M5)], "t")
    store.insert(
        [
            Candle(
                "BTCUSDT",
                Timeframe.M5,
                datetime(2024, 1, 1, 0, m, tzinfo=UTC),
                *(Decimal(1),) * 4,
                Decimal(1),
                True,
            )
            for m in (0, 5, 10, 15)
        ],
        "t",
    )
    tens = store.load(
        "BTCUSDT", Timeframe.M10, start_ms=int(datetime(2024, 1, 1, tzinfo=UTC).timestamp() * 1000)
    )
    assert [k.timeframe for k in tens] == [Timeframe.M10, Timeframe.M10]
    store.close()


# --- universe -------------------------------------------------------------------------------
def test_universe_ranks_by_liquidity_with_anchors_first() -> None:
    members = [
        UniverseMember("XRPUSDT", "XRP-USDT-SWAP", 0.0001, 0, 5e8, False),
        UniverseMember("DOGEUSDT", "DOGE-USDT-SWAP", 0.00001, 0, 4e8, False),
        UniverseMember("SOLUSDT", "SOL-USDT-SWAP", 0.01, 0, 1e9, True),
        UniverseMember("BTCUSDT", "BTC-USDT-SWAP", 0.1, 0, 5e9, True),
        UniverseMember("ETHUSDT", "ETH-USDT-SWAP", 0.01, 0, 6e9, True),
    ]
    assert [m.symbol for m in rank(members, extra=1)] == [
        "BTCUSDT",
        "ETHUSDT",
        "SOLUSDT",
        "XRPUSDT",
    ]
    now = 1_800_000_000_000
    base = {
        "state": "live",
        "ctType": "linear",
        "settleCcy": "USDT",
        "instCategory": "1",
        "instId": "X-USDT-SWAP",
    }
    assert eligible({**base, "listTime": now - 500 * 86_400_000}, now, 400)
    assert not eligible({**base, "listTime": now - 100 * 86_400_000}, now, 400)  # too young
    assert not eligible({**base, "instCategory": "4", "listTime": 0}, now, 400)  # not crypto


# --- walk-forward -------------------------------------------------------------------------
def test_walk_forward_windows_are_chronological_and_disjoint() -> None:
    end = 1_791_000_000
    wins = make_windows(end, count=3, block_days=91)
    assert [w.name for w in wins] == ["W1", "W2", "W3"]
    for a, b in pairwise(wins):
        assert a.end == b.start  # contiguous, no overlap
    assert wins[-1].end == end + 1
    assert all(w.end - w.start == 91 * DAY for w in wins)
    assert window_of(wins[0].start - 1, wins) == "pre"
    assert window_of(wins[1].start, wins) == "W2"


def _sig(template: Signal, t: int, r: float, symbol: str = "BTCUSDT") -> Signal:
    return replace(
        template,
        confirmed_time=t,
        net_r=r,
        gross_r=r + 0.1,
        symbol=symbol,
        entered_time=t,
        exit_reason=ExitReason.TP3 if r > 0 else ExitReason.STOP,
        state=SignalState.TP3_HIT if r > 0 else SignalState.STOPPED,
    )


def test_development_never_overlaps_validation(
    research: tuple[SeriesResearch, list[Signal]],
) -> None:
    template = research[1][0]
    wins = make_windows(1_000_000 * DAY, count=3, block_days=10)
    trades = [_sig(template, wins[0].start - 5 * DAY + k * DAY, 1.0) for k in range(40)]
    for w in wins:
        dev, val = development(trades, w), validation(trades, w)
        assert all(s.confirmed_time < w.start for s in dev)
        assert all(w.start <= s.confirmed_time < w.end for s in val)
        assert not {id(s) for s in dev} & {id(s) for s in val}


def test_insufficient_sample_and_acceptance_rules(
    research: tuple[SeriesResearch, list[Signal]],
) -> None:
    template = research[1][0]
    wins = make_windows(1_000_000 * DAY, count=3, block_days=10)
    few = [_sig(template, w.start + DAY, 1.0) for w in wins]
    assert assess(few, wins).status == "INSUFFICIENT_SAMPLE"
    assert stats(few)["sample"] == "INSUFFICIENT_SAMPLE"
    # 60 trades per window, 2 symbols, all windows positive -> PASS
    good = [
        _sig(
            template,
            w.start + (k % 9) * DAY + k,
            1.0 if k % 2 else -0.5,
            "BTCUSDT" if k % 3 else "XRPUSDT",
        )
        for w in wins
        for k in range(60)
    ]
    assert len(good) >= MIN_VALIDATION_TRADES
    assert assess(good, wins, fresh_symbols=frozenset({"XRPUSDT"})).status == "PASS"
    # one negative window -> FAIL (stability across windows is required)
    bad = [replace(s, net_r=-1.0) if wins[1].contains(s.confirmed_time) else s for s in good]
    a = assess(bad, wins)
    assert a.status == "FAIL" and any("W2" in r for r in a.reasons)


# --- pass 1 / pass 2 ------------------------------------------------------------------------
def test_research_pipeline_reproduces_the_canonical_replay(
    research: tuple[SeriesResearch, list[Signal]],
) -> None:
    series, canonical = research
    trades = run(LENIENT_VARIANT, series)
    key = [(s.id, s.state, s.net_r) for s in trades]
    assert key and key == [(s.id, s.state, s.net_r) for s in canonical]


def test_family_isolation(research: tuple[SeriesResearch, list[Signal]]) -> None:
    series, _ = research
    seen = set()
    for fam in ALL_FAMILIES:
        trades = run(replace(LENIENT_VARIANT, name=fam, families=(fam,)), series)
        assert all(s.family.value == fam for s in trades)
        seen |= {s.family.value for s in trades}
    assert seen  # at least one family produced trades on the fixture


def test_cost_scenarios_change_net_not_gross(research: tuple[SeriesResearch, list[Signal]]) -> None:
    series, _ = research
    out = {c: run(replace(LENIENT_VARIANT, name=c, costs=c), series) for c in COSTS}
    ids = {c: [s.id for s in v] for c, v in out.items()}
    assert ids["low"] == ids["base"] == ids["high"]  # identical trades
    entered = [k for k, s in enumerate(out["base"]) if s.net_r is not None]
    for k in entered:
        assert out["low"][k].gross_r == out["base"][k].gross_r == out["high"][k].gross_r
        assert out["low"][k].net_r >= out["base"][k].net_r >= out["high"][k].net_r  # type: ignore[operator]


def test_timeframe_isolation_and_variant_versions() -> None:
    assert BASELINE.version == BASELINE_VERSION == "wese-trade-signal-4.0-f26f636443"
    v = Variant("x", families=("TREND_CONTINUATION",))
    assert v.version.startswith("wese-trade-research-4.1-") and v.version != BASELINE.version
    assert replace(v, name="renamed", notes="n").version == v.version  # name is not the strategy
    assert replace(v, threshold=70.0).version != v.version
    assert replace(v, costs="high").version != v.version
    with pytest.raises(ValueError, match="entry models"):
        Variant("bad", entry="zone", stop="B").plan_key()


# --- entry refinement / LTF -------------------------------------------------------------------
def test_retrace_entry_uses_only_the_confirmation_candle(
    research: tuple[SeriesResearch, list[Signal]],
) -> None:
    series, _ = research
    trig, rec = next(
        (t, h)
        for t in series.triggers
        for h in t.hyps
        if isinstance(h.plans["close/A/A"], TradePlan)
    )
    market = rec.plans["close/A/A"]
    assert isinstance(market, TradePlan) and market.entry_model is EntryModel.MARKET
    sig = SimpleNamespace(plan=market, side=Side(rec.side))
    bar = series.bars[trig.index]
    plan = retrace_plan(market, bar, series.tick, LENIENT)
    sign = sig.side.sign
    floor = (
        LENIENT.min_risk_cost_multiple * LENIENT.round_trip_cost_rate() * sig.plan.preferred_entry
    )
    assert sign * (sig.plan.preferred_entry - plan.preferred_entry) >= 0  # never worse than close
    assert sign * (plan.preferred_entry - plan.stop) >= floor * 0.999  # cost floor kept
    assert plan.stop == sig.plan.stop and [t.price for t in plan.targets] == [
        t.price for t in sig.plan.targets
    ]
    # bars after confirmation cannot influence the limit
    shifted = replace(series, bars=series.bars[: trig.index + 1])
    assert retrace_plan(sig.plan, shifted.bars[trig.index], series.tick, LENIENT) == plan


def _bar(i: int, t: int, o: float, h: float, lo: float, c: float) -> Bar:
    return Bar(i, t, t + 300, o, h, lo, c, 1.0)


def test_ltf_entry_never_precedes_htf_confirmation(
    research: tuple[SeriesResearch, list[Signal]],
) -> None:
    _, canonical = research
    template = next(s for s in canonical if s.side is Side.LONG and s.entered)
    t0 = 1_700_000_100 // 900 * 900
    plan = replace(template.plan, preferred_entry=100.0, stop=95.0, risk=5.0)
    t1, t2, t3 = (
        replace(tg, price=p) for tg, p in zip(plan.targets, (110.0, 115.0, 120.0), strict=True)
    )
    plan = replace(plan, targets=(t1, t2, t3))
    sig = replace(template, plan=plan, confirmed_time=t0, entry_price=100.0, side=Side.LONG)
    bars5 = [_bar(i, t0 - 600 + i * 300, 100, 101, 99, 100) for i in range(40)]
    # a bullish 5m CHoCH confirmed BEFORE / AT the HTF confirmation, and one after it
    before = TriggerRecord(1, t0 - 300, None, [], [("internal", "CHOCH", "bullish")])  # type: ignore[arg-type]
    at = TriggerRecord(1, t0, None, [], [("internal", "CHOCH", "bullish")])  # type: ignore[arg-type]
    after = TriggerRecord(5, bars5[5].close_time, None, [], [("internal", "CHOCH", "bullish")])  # type: ignore[arg-type]
    ltf = SeriesResearch("BTCUSDT", "5m", 0.1, bars5, [before, at, after])
    a5, d5, counts = ltf_entries([sig], ltf, Timeframe.M15, DEFAULT_SIGNAL_CONFIG)
    assert counts["d_filled"] == 1 and len(a5) == 1
    assert d5[0].entered_time == bars5[5].close_time > t0  # strictly after confirmation
    # without a post-confirmation CHoCH there is no LTF entry at all
    ltf_none = replace(ltf, triggers=[before, at])
    _, d_none, c_none = ltf_entries([sig], ltf_none, Timeframe.M15, DEFAULT_SIGNAL_CONFIG)
    assert d_none == [] and c_none["d_no_choch"] == 1


# --- score models / calibration -----------------------------------------------------------------
def _hyp(values: dict[str, float], pens: dict[str, float]) -> Hypothesis:
    trig = Trigger("t", 0, "internal", "BOS", "bullish", None, None, 0.0)
    return Hypothesis(
        family=ALL_FAMILIES[0],  # type: ignore[arg-type]
        side=Side.LONG,
        trigger=trig,
        components=tuple(Component(k, v, 10.0, v * 10) for k, v in values.items()),
        penalties=tuple(Penalty(k, p, "x") for k, p in pens.items()),
        base_score=0.0,
        score=50.0,
        positive=(),
        negative=(),
        regime=None,
    )


def test_score_model_rescoring() -> None:
    hyp = _hyp(
        {"htf": 1.0, "trend": 0.5, "momentum": 0.0}, {"overextended": 6.0, "adverse_sweep": 6.0}
    )
    assert ScoreModel("baseline").score(hyp) == 50.0  # recorded engine score
    m = ScoreModel("m", weights=(("htf", 3.0), ("trend", 1.0)), penalty_codes=("overextended",))
    # (3*1 + 1*0.5) / 4 = 87.5 ; momentum has no weight ; only the kept penalty applies
    assert m.score(hyp) == pytest.approx(87.5 - 6.0)
    # categories missing on a hypothesis are excluded from normalization (like the engine)
    assert ScoreModel("h", weights=(("structure", 5.0), ("htf", 1.0))).score(hyp) == pytest.approx(
        100.0 - 12.0
    )


def test_calibration_buckets(research: tuple[SeriesResearch, list[Signal]]) -> None:
    template = research[1][0]
    wins = make_windows(1_000_000 * DAY, count=3, block_days=10)
    trades = [
        replace(_sig(template, wins[0].start + k, 1.0), score=float(s))
        for k, s in enumerate((61, 66, 72, 78, 82, 88, 95, 95))
    ]
    rows = calibration(trades, wins)
    assert [r["bucket"] for r in rows] == [
        "60-64",
        "65-69",
        "70-74",
        "75-79",
        "80-84",
        "85-89",
        "90+",
    ]
    assert [r["n"] for r in rows] == [1, 1, 1, 1, 1, 1, 2]
    assert all(r["sample"] == "INSUFFICIENT_SAMPLE" for r in rows)
