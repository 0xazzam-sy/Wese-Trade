"""Forward-test metrics and the conservative pass/fail assessment (pure functions).

A CLOSED trade = an entered signal that reached a final state through the market
(TP3, stop, time stop). Unfilled/expired/invalidated setups, run-stop closures
(END_OF_DATA) and suppressed evaluations are never counted as closed trades.
Primary metrics are expectancy, profit factor, drawdown, average R and sample size; win
rate is shown but never decides anything.
"""

from __future__ import annotations

import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from typing import Any

from app.backtesting.metrics import compute
from app.forward_test.candidate import Criteria
from app.market_data.timeframes import Timeframe
from app.signal_engine.config import SignalConfig
from app.signal_engine.enums import ExitReason, SignalState
from app.signal_engine.lifecycle import compute_r
from app.signal_engine.models import Signal

SCORE_BUCKETS = (
    (75.0, 80.0, "75-79"),
    (80.0, 85.0, "80-84"),
    (85.0, 90.0, "85-89"),
    (90.0, 101.0, "90+"),
)
OPEN_STATES = {SignalState.CONFIRMED, SignalState.ACTIVE, SignalState.TP1_HIT, SignalState.TP2_HIT}


def is_closed_trade(s: Signal) -> bool:
    return (
        s.state.is_final
        and s.entered
        and s.net_r is not None
        and s.exit_reason is not ExitReason.END_OF_DATA
    )


def closed_trades(signals: Sequence[Signal]) -> list[Signal]:
    return sorted((s for s in signals if is_closed_trade(s)), key=lambda s: s.closed_time or 0)


def cost_breakdown(s: Signal, cfg: SignalConfig) -> tuple[float | None, float | None]:
    """(fees in R, slippage in R) of a closed trade: gross - net split by component."""
    if s.gross_r is None or s.net_r is None:
        return None, None
    no_slip = replace(s, exits=list(s.exits))
    compute_r(no_slip, cfg.with_changes(slippage_rate=0.0))
    if no_slip.net_r is None:  # pragma: no cover - entered trades always have R
        return None, None
    return round(s.gross_r - no_slip.net_r, 4), round(no_slip.net_r - s.net_r, 4)


def stats(trades: Sequence[Signal]) -> dict[str, Any]:
    st = compute(list(trades)).as_dict()
    hours = [s.bars_held * Timeframe(s.timeframe).seconds / 3600 for s in trades if s.bars_held]
    st["avg_hold_hours"] = round(statistics.fmean(hours), 2) if hours else None
    return st


def _group(trades: Sequence[Signal], key: Callable[[Signal], str]) -> dict[str, dict[str, Any]]:
    buckets: dict[str, list[Signal]] = {}
    for s in trades:
        buckets.setdefault(key(s), []).append(s)
    return {k: stats(v) for k, v in sorted(buckets.items())}


def score_bucket(score: float) -> str:
    for lo, hi, name in SCORE_BUCKETS:
        if lo <= score < hi:
            return name
    return "<75"


def summary(signals: Sequence[Signal], criteria: Criteria) -> dict[str, Any]:
    closed = closed_trades(signals)
    counts = {
        "confirmed": len(signals),
        "active": sum(1 for s in signals if s.state in OPEN_STATES),
        "closed_trades": len(closed),
        "wins": sum(1 for s in closed if (s.net_r or 0) > 0),
        "losses": sum(1 for s in closed if (s.net_r or 0) <= 0),
        "ambiguous": sum(1 for s in closed if s.ambiguous),
        "expired_unfilled": sum(1 for s in signals if s.state is SignalState.EXPIRED),
        "invalidated": sum(1 for s in signals if s.state is SignalState.INVALIDATED),
        "ended_by_run_stop": sum(1 for s in signals if s.exit_reason is ExitReason.END_OF_DATA),
    }
    return {
        "counts": counts,
        "all": stats(closed),
        "recent": stats(closed[-criteria.recent_trades :]),
        "by_timeframe": _group(closed, lambda s: s.timeframe),
        "by_symbol": _group(closed, lambda s: s.symbol),
        "by_regime": _group(closed, lambda s: s.regime or "unknown"),
        "by_side": _group(closed, lambda s: s.side.value),
        "by_score_bucket": _group(closed, lambda s: score_bucket(s.score)),
    }


@dataclass(frozen=True, slots=True)
class Assessment:
    verdict: str  # INSUFFICIENT_SAMPLE | CONTINUE | PASS_CRITERIA_MET | FAIL_CRITERIA_MET
    reasons: tuple[str, ...]


def _without_best(trades: Sequence[Signal], key: Callable[[Signal], str]) -> float | None:
    totals: dict[str, float] = {}
    for s in trades:
        totals[key(s)] = totals.get(key(s), 0.0) + (s.net_r or 0.0)
    if len(totals) < 2:
        return None  # a single group: "depends on one" by definition
    best = max(totals, key=lambda k: totals[k])
    rest = [s for s in trades if key(s) != best]
    return compute(rest).expectancy


def assess(signals: Sequence[Signal], elapsed_days: float, criteria: Criteria) -> Assessment:
    """Conservative decision support. PASS requires EVERY condition; FAIL requires a
    sufficient sample AND materially negative evidence. Never decided by win rate."""
    closed = closed_trades(signals)
    n = len(closed)
    st = compute(closed)
    exp, pf, dd = st.expectancy, st.profit_factor, st.max_drawdown_r
    dd_limit = max(criteria.max_drawdown_floor_r, criteria.max_drawdown_fraction * n)
    # --- failure (needs real evidence; one unlucky streak is not enough) -------------------
    if n >= criteria.fail_min_trades:
        fail = []
        if exp is not None and exp <= criteria.fail_expectancy:
            fail.append(f"expectancy {exp:+.3f}R <= {criteria.fail_expectancy:+.2f}R")
        if pf is not None and pf <= criteria.fail_profit_factor:
            fail.append(f"profit factor {pf:.2f} <= {criteria.fail_profit_factor:.2f}")
        if dd > 1.5 * dd_limit:
            fail.append(f"drawdown {dd:.1f}R > 1.5 x limit {dd_limit:.1f}R")
        by_tf = _group(closed, lambda s: s.timeframe)
        by_sym = _group(closed, lambda s: s.symbol)
        neg_tf = all((v["expectancy"] or 0) < 0 for v in by_tf.values())
        neg_sym = sum(1 for v in by_sym.values() if (v["expectancy"] or 0) < 0) >= 0.75 * len(
            by_sym
        )
        if exp is not None and exp < 0 and neg_tf and neg_sym:
            fail.append("broad deterioration: every timeframe and >= 75% of symbols negative")
        if len(fail) >= 2 or (fail and n >= criteria.min_closed_trades):
            return Assessment("FAIL_CRITERIA_MET", tuple(fail))
    # --- sample + duration --------------------------------------------------------------------
    if n < criteria.min_closed_trades or elapsed_days < criteria.min_days:
        return Assessment(
            "INSUFFICIENT_SAMPLE",
            (
                f"closed trades {n}/{criteria.min_closed_trades}, "
                f"elapsed {elapsed_days:.1f}/{criteria.min_days} days",
            ),
        )
    # --- pass: every condition --------------------------------------------------------------
    missing = []
    if exp is None or exp <= 0:
        missing.append(f"net expectancy {exp} <= 0")
    if pf is None or pf < criteria.min_profit_factor:
        missing.append(f"profit factor {pf} < {criteria.min_profit_factor}")
    if dd > dd_limit:
        missing.append(f"max drawdown {dd:.1f}R > limit {dd_limit:.1f}R")
    sym = _without_best(closed, lambda s: s.symbol)
    if sym is None or sym <= 0:
        missing.append("depends on one symbol (expectancy without the best symbol <= 0)")
    tf = _without_best(closed, lambda s: s.timeframe)
    if tf is None or tf <= 0:
        missing.append("depends on one timeframe (expectancy without the best timeframe <= 0)")
    recent = compute(closed[-criteria.recent_trades :]).expectancy
    if recent is None or recent < criteria.recent_min_expectancy:
        missing.append(f"recent {criteria.recent_trades} trades expectancy {recent} deteriorated")
    if missing:
        return Assessment("CONTINUE", tuple(missing))
    return Assessment("PASS_CRITERIA_MET", ())
