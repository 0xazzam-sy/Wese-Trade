"""Break of Structure (BOS) and Change of Character (CHoCH), per layer (swing / internal).

Definitions (Wese Trade — one deterministic definition each):

* Every confirmed pivot is a candidate break level until a candle CLOSES beyond it
  (it is then "consumed"). Wick-only penetration never breaks structure (sweeps do that).
* NEUTRAL (no structure yet): the up-level is the most recent unconsumed pivot high, the
  down-level the most recent unconsumed pivot low. The first close beyond either is a BOS
  and sets the structure direction.
* BULLISH structure:
    - BOS (bullish): close above the HIGHEST unconsumed pivot high formed after the last
      broken level. Closes above lower pivots in between consume them silently, so a
      pull-back's minor highs never produce extra events.
    - CHoCH (bearish): close below the PROTECTED LOW (see protected_levels.py).
      A close below an ordinary higher low is NOT a CHoCH.
* BEARISH structure mirrors this (BOS = close below the lowest unconsumed pivot low,
  bullish CHoCH = close above the protected high).
* After any break, pivots formed at or before the broken level are discarded on that
  side: structure restarts from the break.

Layer differences (the only ones):
* SWING (slow, `trailing=False`): the BOS level is the most extreme unconsumed pivot
  since the last break (the structure high/low); the protected level changes only at a
  break (it is the origin of the breaking move).
* INTERNAL (fast, `trailing=True`): the BOS level is the MOST RECENT unconsumed internal
  pivot, and the protected level trails: every newly confirmed, unconsumed internal pivot
  low (bullish) / high (bearish) formed after the current protected level replaces it
  (the old one becomes "superseded"). An internal CHoCH is therefore a close through the
  latest internal higher-low / lower-high — minor by design, and labeled `internal`.

Events are emitted at the close of the break candle and are immutable afterwards.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from app.analysis.enums import (
    FeatureStatus,
    PivotSide,
    StructureDirection,
    StructureEventType,
    StructureLayer,
)
from app.analysis.models import DevelopingBreak, Pivot, ProtectedLevel, StructureEvent
from app.analysis.series import Bar, BarSeries
from app.analysis.structure.protected_levels import leg_extreme, make_protected

# (bar, move beyond level, bullish) -> (displacement score, relative volume, volume confirmed)
MAX_OPEN_LEVELS = 200

Strength = Callable[[Bar, float, bool], tuple[float, float | None, bool]]


@dataclass(frozen=True, slots=True)
class Level:
    price: float
    index: int
    time: int
    protected: bool  # True when the level is a protected high/low (CHoCH level)


@dataclass(frozen=True, slots=True)
class BreakResult:
    event: StructureEvent
    origin: Bar  # leg extreme the move started from (feeds order blocks)


class StructureTracker:
    def __init__(self, layer: StructureLayer, max_pivots: int, *, trailing: bool = False) -> None:
        self.layer = layer
        self.trailing = trailing
        self.direction = StructureDirection.NEUTRAL
        self._highs: list[Pivot] = []  # unconsumed pivot highs, oldest first
        self._lows: list[Pivot] = []
        self.pivots: list[Pivot] = []  # every confirmed pivot (bounded), for output
        self.events: list[StructureEvent] = []
        self.protected_high: ProtectedLevel | None = None
        self.protected_low: ProtectedLevel | None = None
        self.protected_history: list[ProtectedLevel] = []
        self._max_pivots = max_pivots
        self.counts = {"bos": 0, "choch": 0}

    # --- inputs ------------------------------------------------------------------------
    def add_pivot(self, pivot: Pivot, series: BarSeries) -> None:
        self.pivots.append(pivot)
        if len(self.pivots) > self._max_pivots:
            del self.pivots[: len(self.pivots) - self._max_pivots]
        # A pivot already closed through between its bar and its confirmation is consumed.
        after = series.window(pivot.index + 1, pivot.confirmed_index)
        high = pivot.side is PivotSide.HIGH
        if any((b.close > pivot.price) if high else (b.close < pivot.price) for b in after):
            return  # consumed before it was even confirmed
        (self._highs if high else self._lows).append(pivot)
        if self.trailing:
            self._trail(pivot)

    def _trail(self, pivot: Pivot) -> None:
        current = None
        if pivot.side is PivotSide.LOW and self.direction is StructureDirection.BULLISH:
            current = self.protected_low
        elif pivot.side is PivotSide.HIGH and self.direction is StructureDirection.BEARISH:
            current = self.protected_high
        if current is None or pivot.index <= current.index:
            return
        bar_time = pivot.confirmed_time
        self._end(current, "superseded", bar_time)
        level = ProtectedLevel(
            id=f"{self.layer.value}:protected:{pivot.side.value}:{pivot.time}:{bar_time}",
            layer=self.layer,
            side=pivot.side,
            price=pivot.price,
            index=pivot.index,
            time=pivot.time,
            created_time=bar_time,
        )
        if pivot.side is PivotSide.LOW:
            self.protected_low = level
        else:
            self.protected_high = level
        self._remember(level)

    # --- levels ------------------------------------------------------------------------
    def up_level(self) -> Level | None:
        if self.direction is StructureDirection.BEARISH:
            p = self.protected_high
            return Level(p.price, p.index, p.time, True) if p else None
        if not self._highs:
            return None
        if self.direction is StructureDirection.BULLISH and not self.trailing:
            pivot = max(self._highs, key=lambda x: (x.price, x.index))
        else:
            pivot = self._highs[-1]
        return Level(pivot.price, pivot.index, pivot.time, False)

    def down_level(self) -> Level | None:
        if self.direction is StructureDirection.BULLISH:
            p = self.protected_low
            return Level(p.price, p.index, p.time, True) if p else None
        if not self._lows:
            return None
        if self.direction is StructureDirection.BEARISH and not self.trailing:
            pivot = min(self._lows, key=lambda x: (x.price, -x.index))
        else:
            pivot = self._lows[-1]
        return Level(pivot.price, pivot.index, pivot.time, False)

    # --- per closed bar ----------------------------------------------------------------
    def on_bar(self, bar: Bar, series: BarSeries, strength: Strength) -> BreakResult | None:
        result: BreakResult | None = None
        up, down = self.up_level(), self.down_level()
        if up is not None and bar.close > up.price:
            result = self._break(bar, series, up, bullish=True, strength=strength)
        elif down is not None and bar.close < down.price:
            result = self._break(bar, series, down, bullish=False, strength=strength)
        # Consume every pivot this close went through (silently if it was not the level).
        self._highs = [p for p in self._highs if p.price >= bar.close][-MAX_OPEN_LEVELS:]
        self._lows = [p for p in self._lows if p.price <= bar.close][-MAX_OPEN_LEVELS:]
        return result

    def _break(
        self, bar: Bar, series: BarSeries, level: Level, *, bullish: bool, strength: Strength
    ) -> BreakResult:
        previous = self.direction
        opposite = StructureDirection.BEARISH if bullish else StructureDirection.BULLISH
        event_type = StructureEventType.CHOCH if previous is opposite else StructureEventType.BOS
        direction = StructureDirection.BULLISH if bullish else StructureDirection.BEARISH
        displacement, relvol, vol_ok = strength(bar, bar.close - level.price, bullish)
        event = StructureEvent(
            id=f"{self.layer.value}:{event_type.value}:{direction.value}:{bar.time}",
            layer=self.layer,
            type=event_type,
            direction=direction,
            level=level.price,
            level_index=level.index,
            level_time=level.time,
            index=bar.index,
            time=bar.time,
            confirmed_time=bar.close_time,
            close=bar.close,
            displacement=displacement,
            relative_volume=relvol,
            volume_confirmed=vol_ok,
        )
        self.events.append(event)
        self.counts["choch" if event_type is StructureEventType.CHOCH else "bos"] += 1
        origin_side = PivotSide.LOW if bullish else PivotSide.HIGH
        origin = leg_extreme(series, level.index, bar.index, origin_side)
        new_level = make_protected(self.layer, origin_side, origin, bar.close_time)
        # Lifecycle of protected levels (forward-only).
        if bullish:
            if self.protected_high is not None:
                self._end(self.protected_high, "broken", bar.close_time)
                self.protected_high = None
            if self.protected_low is not None:
                self._end(self.protected_low, "superseded", bar.close_time)
            self.protected_low = new_level
            self._highs = [p for p in self._highs if p.index > level.index]
        else:
            if self.protected_low is not None:
                self._end(self.protected_low, "broken", bar.close_time)
                self.protected_low = None
            if self.protected_high is not None:
                self._end(self.protected_high, "superseded", bar.close_time)
            self.protected_high = new_level
            self._lows = [p for p in self._lows if p.index > level.index]
        self._remember(new_level)
        self.direction = direction
        return BreakResult(event, origin)

    def _remember(self, level: ProtectedLevel) -> None:
        self.protected_history.append(level)
        if len(self.protected_history) > 50:
            del self.protected_history[:-50]

    @staticmethod
    def _end(level: ProtectedLevel, status: str, when: int) -> None:
        level.status = status
        level.ended_time = when

    # --- forming candle (read-only) ---------------------------------------------------------
    def developing(self, price: float) -> list[DevelopingBreak]:
        up, down = self.up_level(), self.down_level()
        out: list[DevelopingBreak] = []
        for level, bullish in ((up, True), (down, False)):
            if level is None or not (price > level.price if bullish else price < level.price):
                continue
            opposite = StructureDirection.BEARISH if bullish else StructureDirection.BULLISH
            out.append(
                DevelopingBreak(
                    layer=self.layer,
                    type=StructureEventType.CHOCH
                    if self.direction is opposite
                    else StructureEventType.BOS,
                    direction=StructureDirection.BULLISH if bullish else StructureDirection.BEARISH,
                    level=level.price,
                    price=price,
                    status=FeatureStatus.DEVELOPING,
                )
            )
        return out
