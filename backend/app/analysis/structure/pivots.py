"""Fractal pivot detection with explicit confirmation delay (no hidden repainting).

A pivot HIGH at bar i (layer with `left`/`right`):
    high[i] >  every high in [i-left, i-1]     (strict: the FIRST of equal highs wins)
    high[i] >= every high in [i+1, i+right]
It is CONFIRMED at the close of bar i+right (`confirmed_time`) and never changes after that.
Before confirmation it may be reported as DEVELOPING (it can still disappear).
Pivot LOWs mirror this.

Classification against the previous confirmed pivot of the same side and layer:
HH/LH for highs, HL/LL for lows; HIGH/LOW for the first one or an exact tie.
"""

from __future__ import annotations

from app.analysis.enums import FeatureStatus, PivotSide, PivotType, StructureLayer
from app.analysis.models import Pivot
from app.analysis.series import Bar, BarSeries


def _classify(side: PivotSide, price: float, previous: float | None) -> PivotType:
    if side is PivotSide.HIGH:
        if previous is None or price == previous:
            return PivotType.HIGH
        return PivotType.HH if price > previous else PivotType.LH
    if previous is None or price == previous:
        return PivotType.LOW
    return PivotType.HL if price > previous else PivotType.LL


def _is_high(center: Bar, left: list[Bar], right: list[Bar]) -> bool:
    return all(center.high > b.high for b in left) and all(center.high >= b.high for b in right)


def _is_low(center: Bar, left: list[Bar], right: list[Bar]) -> bool:
    return all(center.low < b.low for b in left) and all(center.low <= b.low for b in right)


class PivotDetector:
    def __init__(self, layer: StructureLayer, left: int, right: int) -> None:
        self.layer = layer
        self.left = left
        self.right = right
        self.last_high: float | None = None
        self.last_low: float | None = None
        self.count = 0

    def _make(
        self, side: PivotSide, bar: Bar, confirm: Bar | None, status: FeatureStatus, step: int
    ) -> Pivot:
        price = bar.high if side is PivotSide.HIGH else bar.low
        previous = self.last_high if side is PivotSide.HIGH else self.last_low
        confirmed_index = confirm.index if confirm else bar.index + self.right
        confirmed_time = confirm.close_time if confirm else bar.time + (self.right + 1) * step
        return Pivot(
            id=f"{self.layer.value}:pivot:{side.value}:{bar.time}",
            layer=self.layer,
            side=side,
            type=_classify(side, price, previous),
            price=price,
            index=bar.index,
            time=bar.time,
            confirmed_index=confirmed_index,
            confirmed_time=confirmed_time,
            status=status,
        )

    def update(self, series: BarSeries, n: int) -> list[Pivot]:
        """Call once per appended closed bar `n`. Returns pivots CONFIRMED at bar n."""
        i = n - self.right
        if i - self.left < series.first_index:
            return []
        window = series.window(i - self.left, n)
        center = window[self.left]
        left, right = window[: self.left], window[self.left + 1 :]
        confirm = window[-1]
        step = confirm.close_time - confirm.time
        found: list[Pivot] = []
        if _is_high(center, left, right):
            pivot = self._make(PivotSide.HIGH, center, confirm, FeatureStatus.CONFIRMED, step)
            self.last_high = pivot.price
            found.append(pivot)
        if _is_low(center, left, right):
            pivot = self._make(PivotSide.LOW, center, confirm, FeatureStatus.CONFIRMED, step)
            self.last_low = pivot.price
            found.append(pivot)
        self.count += len(found)
        return found

    def developing(self, series: BarSeries, forming: Bar | None) -> list[Pivot]:
        """Unconfirmed candidates among the last `right` closed bars (+ forming bar).

        At most one high and one low (the most recent valid candidate of each)."""
        if len(series) == 0:
            return []
        n = len(series) - 1
        tail = series.window(n - self.right - self.left + 1, n)
        bars = [*tail, forming] if forming is not None else tail
        step = bars[-1].close_time - bars[-1].time
        out: list[Pivot] = []
        for side in (PivotSide.HIGH, PivotSide.LOW):
            test = _is_high if side is PivotSide.HIGH else _is_low
            for pos in range(len(bars) - 1, self.left - 1, -1):
                center = bars[pos]
                if center.index <= n - self.right:
                    break  # old enough to have been decided already
                left = bars[pos - self.left : pos]
                right = bars[pos + 1 :]
                if len(left) == self.left and test(center, left, right):
                    out.append(self._make(side, center, None, FeatureStatus.DEVELOPING, step))
                    break
        return out
