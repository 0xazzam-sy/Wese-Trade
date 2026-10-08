"""Swings, market structure (HH/HL/LH/LL, BOS, CHoCH) and liquidity pools / sweeps.

A fractal swing at candle j (n candles on each side) is CONFIRMED only at candle j + n, so
nothing here looks ahead.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field


@dataclass(slots=True)
class Swing:
    index: int
    time: int  # open time of the swing candle (ms)
    price: float
    high: bool  # True = swing high, False = swing low
    label: str = ""  # HH / LH / HL / LL
    major: bool = False


@dataclass(slots=True)
class Pool:
    """Resting liquidity beyond an unswept swing (buy-side above highs, sell-side below lows)."""

    price: float
    above: bool  # True = buy-side liquidity above price (سيولة علوية)
    index: int
    time: int
    equal: bool = False  # EQH / EQL
    swept_index: int | None = None


@dataclass(slots=True)
class StructureEvent:
    index: int
    time: int
    kind: str  # BOS / CHOCH
    direction: int  # +1 bullish, -1 bearish
    level: float


@dataclass
class StructureTracker:
    n: int  # fractal size (minor)
    highs: list[Swing] = field(default_factory=list)
    lows: list[Swing] = field(default_factory=list)
    pools: list[Pool] = field(default_factory=list)
    events: deque[StructureEvent] = field(default_factory=lambda: deque(maxlen=12))
    direction: int = 0  # structural trend: +1 bullish, -1 bearish, 0 unknown
    _h: deque[float] = field(default_factory=lambda: deque(maxlen=64))
    _l: deque[float] = field(default_factory=lambda: deque(maxlen=64))
    _t: deque[int] = field(default_factory=lambda: deque(maxlen=64))
    last_sweep: tuple[int, int, float, float] | None = None  # (index, dir, pool, extreme)
    _broken_hi: float | None = None
    _broken_lo: float | None = None

    def reset(self) -> None:
        self.highs.clear()
        self.lows.clear()
        self.pools.clear()
        self.events.clear()
        self._h.clear()
        self._l.clear()
        self._t.clear()
        self.direction = 0
        self.last_sweep = None
        self._broken_hi = self._broken_lo = None

    def update(self, i: int, t: int, h: float, lo: float, c: float, atr: float) -> list[Swing]:
        """Process a closed candle; returns the swings confirmed by it."""
        new: list[Swing] = []
        self._h.append(h)
        self._l.append(lo)
        self._t.append(t)
        n = self.n
        if len(self._h) >= 2 * n + 1:
            k = len(self._h) - 1 - n  # candidate pivot position in the window
            hs, ls = list(self._h), list(self._l)
            j = i - n
            if all(hs[k] > hs[k - d] for d in range(1, n + 1)) and all(
                hs[k] >= hs[k + d] for d in range(1, n + 1)
            ):
                new.append(self._add_swing(Swing(j, self._t[k], hs[k], True), atr))
            if all(ls[k] < ls[k - d] for d in range(1, n + 1)) and all(
                ls[k] <= ls[k + d] for d in range(1, n + 1)
            ):
                new.append(self._add_swing(Swing(j, self._t[k], ls[k], False), atr))
        self._breaks(i, t, c)
        self._sweeps(i, h, lo, c)
        return new

    def _add_swing(self, s: Swing, atr: float) -> Swing:
        same = self.highs if s.high else self.lows
        prev = same[-1] if same else None
        if prev is not None:
            if s.high:
                s.label = "HH" if s.price > prev.price else "LH"
            else:
                s.label = "HL" if s.price > prev.price else "LL"
        same.append(s)
        if len(same) > 40:
            del same[0]
        equal = prev is not None and atr > 0 and abs(prev.price - s.price) <= 0.1 * atr
        self.pools.append(Pool(s.price, s.high, s.index, s.time, equal=equal))
        if len(self.pools) > 60:
            del self.pools[0]
        return s

    def _breaks(self, i: int, t: int, c: float) -> None:
        if self.highs:
            hi = self.highs[-1].price
            if c > hi and self._broken_hi != hi:
                self._broken_hi = hi
                kind = "BOS" if self.direction >= 0 else "CHOCH"
                self.events.append(StructureEvent(i, t, kind, 1, hi))
                self.direction = 1
        if self.lows:
            lo = self.lows[-1].price
            if c < lo and self._broken_lo != lo:
                self._broken_lo = lo
                kind = "BOS" if self.direction <= 0 else "CHOCH"
                self.events.append(StructureEvent(i, t, kind, -1, lo))
                self.direction = -1

    def _sweeps(self, i: int, h: float, lo: float, c: float) -> None:
        for p in self.pools:
            if p.swept_index is not None or p.index >= i:
                continue
            if p.above and h > p.price:
                p.swept_index = i
                if c < p.price:  # wick through, close back below: buy-side sweep (bearish)
                    self.last_sweep = (i, -1, p.price, h)
            elif not p.above and lo < p.price:
                p.swept_index = i
                if c > p.price:  # sell-side sweep (bullish)
                    self.last_sweep = (i, 1, p.price, lo)
        if len(self.pools) > 40:
            self.pools = [p for p in self.pools if p.swept_index is None or i - p.swept_index < 50]

    def active_pools(self, above: bool) -> list[Pool]:
        return [p for p in self.pools if p.above == above and p.swept_index is None]

    def last_event(self) -> StructureEvent | None:
        return self.events[-1] if self.events else None
