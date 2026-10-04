"""Trade statistics in R-multiples (never account P&L, never leverage).

Primary metrics: expectancy (mean net R per entered trade), profit factor, max drawdown
of the cumulative R curve, average/median R. Win rate is reported but is secondary: a
high win rate with a poor payoff is still a bad strategy.
"""

from __future__ import annotations

import statistics
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from typing import Any

from app.signal_engine.enums import ExitReason, SignalClass, SignalState
from app.signal_engine.models import Signal

STRONG = {SignalClass.STRONG_BUY, SignalClass.STRONG_SELL}


@dataclass(frozen=True, slots=True)
class Stats:
    signals: int
    long: int
    short: int
    strong: int
    regular: int
    entered: int
    wins: int
    losses: int
    ambiguous: int
    expired: int
    invalidated: int
    open_at_end: int
    win_rate: float | None
    avg_r: float | None
    median_r: float | None
    expectancy: float | None
    profit_factor: float | None
    max_drawdown_r: float
    total_r: float
    gross_expectancy: float | None
    gross_profit_factor: float | None
    gross_total_r: float
    avg_hold_bars: float | None
    tp1_rate: float | None
    tp2_rate: float | None
    tp3_rate: float | None
    max_consecutive_wins: int
    max_consecutive_losses: int

    def as_dict(self) -> dict[str, Any]:
        return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in asdict(self).items()}


def _pf(values: list[float]) -> float | None:
    gains = sum(v for v in values if v > 0)
    losses = -sum(v for v in values if v < 0)
    if losses == 0:
        return None if gains == 0 else float("inf")
    return gains / losses


def _drawdown(values: list[float]) -> float:
    peak = equity = worst = 0.0
    for v in values:
        equity += v
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return worst


def _streaks(values: list[float]) -> tuple[int, int]:
    best_w = best_l = w = lo = 0
    for v in values:
        if v > 0:
            w, lo = w + 1, 0
        else:
            w, lo = 0, lo + 1
        best_w, best_l = max(best_w, w), max(best_l, lo)
    return best_w, best_l


def compute(signals: Iterable[Signal]) -> Stats:
    items = sorted(signals, key=lambda s: s.confirmed_time)
    complete = [s for s in items if s.exit_reason is not ExitReason.END_OF_DATA]
    entered = [s for s in complete if s.entered and s.net_r is not None]
    net = [s.net_r for s in entered if s.net_r is not None]
    gross = [s.gross_r for s in entered if s.gross_r is not None]
    wins = sum(1 for v in net if v > 0)
    streak_w, streak_l = _streaks(net)
    n = len(entered)
    return Stats(
        signals=len(items),
        long=sum(1 for s in items if s.side.value == "long"),
        short=sum(1 for s in items if s.side.value == "short"),
        strong=sum(1 for s in items if s.signal_class in STRONG),
        regular=sum(1 for s in items if s.signal_class not in STRONG),
        entered=n,
        wins=wins,
        losses=n - wins,
        ambiguous=sum(1 for s in entered if s.ambiguous),
        expired=sum(1 for s in complete if s.state is SignalState.EXPIRED),
        invalidated=sum(1 for s in complete if s.state is SignalState.INVALIDATED),
        open_at_end=len(items) - len(complete),
        win_rate=wins / n if n else None,
        avg_r=statistics.fmean(net) if net else None,
        median_r=statistics.median(net) if net else None,
        expectancy=statistics.fmean(net) if net else None,
        profit_factor=_pf(net),
        max_drawdown_r=_drawdown(net),
        total_r=sum(net),
        gross_expectancy=statistics.fmean(gross) if gross else None,
        gross_profit_factor=_pf(gross),
        gross_total_r=sum(gross),
        avg_hold_bars=statistics.fmean(s.bars_held for s in entered) if entered else None,
        tp1_rate=sum(1 for s in entered if s.targets_hit >= 1) / n if n else None,
        tp2_rate=sum(1 for s in entered if s.targets_hit >= 2) / n if n else None,
        tp3_rate=sum(1 for s in entered if s.targets_hit >= 3) / n if n else None,
        max_consecutive_wins=streak_w,
        max_consecutive_losses=streak_l,
    )


def group(signals: Iterable[Signal], key: Callable[[Signal], str]) -> dict[str, dict[str, Any]]:
    buckets: dict[str, list[Signal]] = {}
    for s in signals:
        buckets.setdefault(key(s), []).append(s)
    return {k: compute(v).as_dict() for k, v in sorted(buckets.items())}
