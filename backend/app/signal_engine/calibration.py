"""Score calibration: does a higher confluence score actually mean better outcomes?

Confirmed historical signals are bucketed by score (70-74, 75-79, ..., 95-100) and each
bucket reports count, win rate, expectancy, profit factor and average R. STRONG classes
are only justified when the top buckets are materially better AND well populated.
"""

from __future__ import annotations

from collections.abc import Iterable
from itertools import pairwise
from typing import Any

from app.backtesting.metrics import compute
from app.signal_engine.models import Signal

BUCKETS = [(70, 75), (75, 80), (80, 85), (85, 90), (90, 95), (95, 101)]


def bucket_label(score: float, buckets: list[tuple[int, int]] = BUCKETS) -> str:
    for lo, hi in buckets:
        if lo <= score < hi:
            return f"{lo}-{min(hi, 100) - (0 if hi > 100 else 1)}"
    return f"<{buckets[0][0]}"


def calibration_table(
    signals: Iterable[Signal], buckets: list[tuple[int, int]] = BUCKETS
) -> list[dict[str, Any]]:
    items = list(signals)
    rows = []
    for lo, hi in [(0, buckets[0][0]), *buckets]:
        chosen = [s for s in items if lo <= s.score < hi]
        stats = compute(chosen)
        rows.append(
            {
                "bucket": f"{lo}-{min(hi, 100) - (0 if hi > 100 else 1)}" if lo else f"<{hi}",
                "signals": stats.signals,
                "entered": stats.entered,
                "win_rate": stats.win_rate,
                "expectancy": stats.expectancy,
                "profit_factor": stats.profit_factor,
                "avg_r": stats.avg_r,
                "gross_expectancy": stats.gross_expectancy,
            }
        )
    return rows


def monotonic_score(rows: list[dict[str, Any]], min_entered: int = 30) -> bool | None:
    """True if expectancy never decreases across well-populated buckets (None: too little data)."""
    values = [
        r["expectancy"] for r in rows if r["entered"] >= min_entered and r["expectancy"] is not None
    ]
    if len(values) < 2:
        return None
    return all(b >= a for a, b in pairwise(values))
