"""Support / resistance engine with level strength (docs/research-scalp6.md §1.1).

Levels are seeded only from CONFIRMED swings. Nearby levels (within `tol` ATR) merge into one
zone. A level's role follows price: below price it is support (دعم), above it resistance
(مقاومة). A decisive close through a level marks it broken; a later reaction from the other
side is a flip (breakout/retest) and adds strength.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

MAX_LEVELS = 24
DECAY_CANDLES = 600.0  # recency half-life-ish scale


@dataclass(slots=True)
class Level:
    price: float
    created: int
    last_touch: int
    touches: int = 1
    rejection: float = 0.0  # summed wick quality of reactions (ATR units, capped)
    volume: float = 1.0  # relative volume at origin
    flips: int = 0
    broken_side: int = 0  # +1 = price closed above it last, -1 = below, 0 = untested
    last_reaction: int = -10
    crossings: int = 0  # decisive closes through the level (choppy levels are discarded)
    away: bool = False  # price moved >= 1 ATR away since the last counted touch
    origin_side: int = 0  # side price was on when the level was seeded
    breakout_used: bool = False  # a breakout setup (family B) already fired on this level

    def strength(self, i: int) -> float:
        age = max(0, i - self.last_touch)
        recency = math.exp(-age / DECAY_CANDLES)
        base = (
            1.0 * min(self.touches, 6)
            + min(self.rejection, 4.0)
            + 1.5 * min(self.flips, 2)
            + 0.5 * min(max(self.volume - 1.0, 0.0), 2.0)
        )
        return round(base * (0.4 + 0.6 * recency), 3)

    def grade(self, i: int) -> str:
        s = self.strength(i)
        # Cut-offs from the strength distribution (p80 / p45 over 25k level samples on
        # BTC 1m, ETH 5m, DOGE 5m development data): ~20% strong, ~35% medium, ~45% weak.
        return "strong" if s >= 7.9 else "medium" if s >= 3.8 else "weak"


class LevelBook:
    def __init__(self, tol: float = 0.3) -> None:
        self.tol = tol
        self.levels: list[Level] = []

    def reset(self) -> None:
        self.levels.clear()

    def seed(self, price: float, i: int, rel_vol: float, atr: float) -> None:
        for lv in self.levels:
            if abs(lv.price - price) <= self.tol * atr:
                total = lv.touches + 1
                lv.price = (lv.price * lv.touches + price) / total
                lv.touches = total
                lv.last_touch = i
                lv.volume = max(lv.volume, rel_vol)
                return
        self.levels.append(Level(price, i, i, volume=rel_vol))
        if len(self.levels) > MAX_LEVELS:
            weakest = min(self.levels, key=lambda lv: lv.strength(i))
            self.levels.remove(weakest)

    def update(self, i: int, h: float, lo: float, c: float, prev_c: float, atr: float) -> None:
        """Touch / rejection / break / flip bookkeeping on a closed candle.

        * a touch counts only on a genuine revisit (price was >= 1 ATR away since the last one);
        * a decisive close (> 0.5 ATR) through the level breaks it and flips its role; a
          level broken back again is chop and is discarded;
        * a flip counts when a crossed level is retested and holds from the other side.
        """
        if atr <= 0:
            return
        band = self.tol * atr
        keep: list[Level] = []
        for lv in self.levels:
            p = lv.price
            if abs(c - p) >= atr:
                lv.away = True
            decisive = 0.5 * atr
            side_now = 1 if c > p + decisive else -1 if c < p - decisive else 0
            if side_now and lv.broken_side == 0 and lv.origin_side == 0:
                lv.origin_side = side_now  # first decisive side seen after seeding
            if side_now and lv.origin_side and side_now != (lv.broken_side or lv.origin_side):
                lv.crossings += 1
                lv.broken_side = side_now
            if lv.crossings >= 2:
                continue  # broken, then broken back: price chops through it
            if lv.away and i - lv.last_reaction >= 3:
                support = lo <= p + band and c > p + band and lo >= p - 2 * band
                resist = h >= p - band and c < p - band and h <= p + 2 * band
                if support or resist:
                    lv.touches += 1
                    wick = (c - lo) if support else (h - c)
                    lv.rejection += min(wick / atr, 1.5)
                    lv.last_touch = lv.last_reaction = i
                    lv.away = False
                    side = 1 if support else -1
                    if lv.broken_side == side and lv.crossings >= 1:
                        lv.flips += 1  # broken, then retested and held from the other side
            keep.append(lv)
        self.levels = keep
        # Prune levels far from price and long untouched.
        if len(self.levels) > MAX_LEVELS // 2 and i % 50 == 0:
            self.levels = [
                lv for lv in self.levels if abs(lv.price - c) <= 12 * atr or i - lv.last_touch < 900
            ]

    def nearest(self, price: float, above: bool, i: int, min_grade: str = "weak") -> list[Level]:
        order = {"weak": 0, "medium": 1, "strong": 2}
        need = order[min_grade]
        side = [
            lv
            for lv in self.levels
            if (lv.price > price if above else lv.price < price) and order[lv.grade(i)] >= need
        ]
        return sorted(side, key=lambda lv: abs(lv.price - price))
