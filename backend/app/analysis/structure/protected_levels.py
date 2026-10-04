"""Protected high / low.

Definition (Wese Trade): when structure breaks UP at candle b through a level formed at
bar p, the PROTECTED LOW is the lowest low of bars [p, b] — the origin of the move that
broke structure. While the structure is bullish, a close below it is a bearish CHoCH.
The protected HIGH mirrors this for downward breaks. A protected level is replaced
("superseded") by the next break in the same direction, or "broken" by a CHoCH.
Computed only from closed bars up to b: no lookahead.
"""

from __future__ import annotations

from app.analysis.enums import PivotSide, StructureLayer
from app.analysis.models import ProtectedLevel
from app.analysis.series import Bar, BarSeries


def leg_extreme(series: BarSeries, start: int, end: int, side: PivotSide) -> Bar:
    """Bar with the lowest low (side=LOW) or highest high in [start, end]; first wins ties."""
    bars = series.window(start, end)
    if side is PivotSide.LOW:
        return min(bars, key=lambda b: (b.low, b.index))
    return max(bars, key=lambda b: (b.high, -b.index))


def make_protected(
    layer: StructureLayer, side: PivotSide, bar: Bar, created_time: int
) -> ProtectedLevel:
    price = bar.low if side is PivotSide.LOW else bar.high
    return ProtectedLevel(
        id=f"{layer.value}:protected:{side.value}:{bar.time}:{created_time}",
        layer=layer,
        side=side,
        price=price,
        index=bar.index,
        time=bar.time,
        created_time=created_time,
    )
