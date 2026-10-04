"""Chronological walk-forward windows, robustness metrics and acceptance rules.

Windows are CALENDAR periods shared by every symbol and timeframe (no shuffling):

    pre-period | W1 | W2 | W3        (each W = `block_days`, W3 ends at the research end)

For validation window Wk the development (training) data is everything strictly before
Wk's start (expanding window). A trade belongs to the window containing its confirmation
time. Development and validation never overlap (tested).

Sample-size rules (docs/research.md):
* a group with fewer than MIN_GROUP_TRADES validation trades is INSUFFICIENT_SAMPLE;
* a candidate needs >= MIN_WINDOW_TRADES in EVERY validation window and
  >= MIN_VALIDATION_TRADES in total before it can pass.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from app.backtesting.metrics import compute, group
from app.signal_engine.models import Signal

DAY = 86_400
MIN_GROUP_TRADES = 50
MIN_WINDOW_TRADES = 30
MIN_VALIDATION_TRADES = 150


@dataclass(frozen=True, slots=True)
class Window:
    name: str
    start: int  # epoch seconds, inclusive
    end: int  # exclusive

    def contains(self, t: int) -> bool:
        return self.start <= t < self.end


def make_windows(end: int, *, count: int = 3, block_days: int = 91) -> list[Window]:
    """`count` consecutive validation windows ending at `end` (exclusive bound + 1s)."""
    out = []
    for k in range(count):
        stop = end + 1 - (count - 1 - k) * block_days * DAY
        out.append(Window(f"W{k + 1}", stop - block_days * DAY, stop))
    return out


def window_of(t: int, windows: Sequence[Window]) -> str:
    for w in windows:
        if w.contains(t):
            return w.name
    return "pre" if t < windows[0].start else "post"


def development(trades: Iterable[Signal], w: Window) -> list[Signal]:
    """Training data for validation window `w`: strictly before its start."""
    return [s for s in trades if s.confirmed_time < w.start]


def validation(trades: Iterable[Signal], w: Window) -> list[Signal]:
    return [s for s in trades if w.contains(s.confirmed_time)]


def stats(trades: Sequence[Signal]) -> dict[str, Any]:
    out = compute(list(trades)).as_dict()
    out["sample"] = "OK" if out["entered"] >= MIN_GROUP_TRADES else "INSUFFICIENT_SAMPLE"
    return out


def grouped(trades: Sequence[Signal], key: Callable[[Signal], str]) -> dict[str, dict[str, Any]]:
    out = group(list(trades), key)
    for v in out.values():
        v["sample"] = "OK" if v["entered"] >= MIN_GROUP_TRADES else "INSUFFICIENT_SAMPLE"
    return out


def per_window(trades: Sequence[Signal], windows: Sequence[Window]) -> dict[str, dict[str, Any]]:
    return {w.name: stats(validation(trades, w)) for w in windows}


def validation_trades(trades: Iterable[Signal], windows: Sequence[Window]) -> list[Signal]:
    return [s for s in trades if any(w.contains(s.confirmed_time) for w in windows)]


@dataclass(frozen=True, slots=True)
class Assessment:
    status: str  # PASS | FAIL | INSUFFICIENT_SAMPLE
    reasons: tuple[str, ...]


def assess(
    trades: Sequence[Signal],
    windows: Sequence[Window],
    *,
    fresh_symbols: frozenset[str] = frozenset(),
) -> Assessment:
    """Research acceptance criteria (Phase 4.1 §33). Not a guarantee of anything."""
    val = validation_trades(trades, windows)
    wins = per_window(trades, windows)
    total = compute(val)
    reasons: list[str] = []
    if total.entered < MIN_VALIDATION_TRADES or any(
        wins[w.name]["entered"] < MIN_WINDOW_TRADES for w in windows
    ):
        counts = ", ".join(f"{w.name}={wins[w.name]['entered']}" for w in windows)
        return Assessment(
            "INSUFFICIENT_SAMPLE",
            (
                f"validation trades {total.entered} ({counts}); need >= {MIN_VALIDATION_TRADES} "
                f"total and >= {MIN_WINDOW_TRADES} per window",
            ),
        )
    for w in windows:
        e, pf = wins[w.name]["expectancy"], wins[w.name]["profit_factor"]
        if e is None or e <= 0:
            reasons.append(
                f"{w.name} expectancy {e:+.3f}R <= 0" if e is not None else f"{w.name} no trades"
            )
        if pf is None or pf <= 1.0:
            reasons.append(f"{w.name} profit factor {pf} <= 1.0")
    if (total.profit_factor or 0) < 1.1:
        reasons.append(f"validation profit factor {total.profit_factor} < 1.1")
    by_symbol = group(val, lambda s: s.symbol)
    if by_symbol:
        best = max(by_symbol, key=lambda k: by_symbol[k]["total_r"])
        rest = compute([s for s in val if s.symbol != best])
        if (rest.expectancy or 0) <= 0:
            reasons.append(f"depends on {best}: expectancy without it {rest.expectancy}")
    if fresh_symbols:
        fresh = compute([s for s in val if s.symbol in fresh_symbols])
        if (fresh.expectancy or 0) <= 0:
            reasons.append(f"fresh (never inspected) symbols expectancy {fresh.expectancy} <= 0")
    if total.max_drawdown_r > max(15.0, 0.2 * total.entered):
        reasons.append(f"drawdown {total.max_drawdown_r:.1f}R exceeds max(15R, 0.2R x trades)")
    return Assessment("FAIL" if reasons else "PASS", tuple(reasons))
