"""Incremental per-stream execution analysis.

Fed the CLOSED bars of the canonical MarketAnalyzer (one update per candle, never a full
recompute). Own indicators: EMA 20/50/200, ATR(14), RSI(14) and the support/resistance book
with level strength (the scalp-6 analysis layer). Structure (BOS / CHoCH, HH/HL/LH/LL),
liquidity sweeps, regime and trend direction are read from the canonical analysis snapshot,
so the execution layer uses exactly what the chart draws.
"""

from __future__ import annotations

from typing import Any

from app.analysis.models import AnalysisSnapshot
from app.analysis.series import Bar
from app.execution.models import Features, Level
from app.scalp6.indicators import Atr, Ema, RollingMean, Rsi
from app.scalp6.levels import LevelBook
from app.scalp6.structure import StructureTracker

LEVELS_SHOWN = 4  # per side


class ExecAnalyzer:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.ema20, self.ema50, self.ema200 = Ema(20), Ema(50), Ema(200)
        self.atr = Atr(14)
        self.rsi = Rsi(14)
        self.vol = RollingMean(20)
        self.swings = StructureTracker(2)
        self.levels = LevelBook()
        self.last_index: int | None = None
        self.prev_close: float | None = None
        self.close_before = 0.0  # close of the bar before the last processed one
        self.ema20_prev: float | None = None
        self.i = -1  # internal counter for the level book
        self.count = 0

    def update(self, bar: Bar) -> bool:
        """Process one closed bar; returns False for a bar already seen."""
        if self.last_index is not None:
            if bar.index <= self.last_index:
                return False
            if bar.index != self.last_index + 1:
                self.reset()  # history gap / reseed: start over (never mix series)
        self.i += 1
        self.count += 1
        self.ema20_prev = self.ema20.value
        prev = self.prev_close if self.prev_close is not None else bar.close
        self.close_before = prev
        atr = self.atr.update(bar.high, bar.low, bar.close)
        self.ema20.update(bar.close)
        self.ema50.update(bar.close)
        self.ema200.update(bar.close)
        self.rsi.update(bar.close)
        mean_v = self.vol.mean if self.vol.window else 0.0
        rel = bar.volume / mean_v if mean_v > 0 else 1.0
        self.vol.update(bar.volume)
        ms = bar.time * 1000
        for sw in self.swings.update(self.i, ms, bar.high, bar.low, bar.close, atr):
            self.levels.seed(sw.price, self.i, rel, atr)
        self.levels.update(self.i, bar.high, bar.low, bar.close, prev, atr)
        self.last_index = bar.index
        self.prev_close = bar.close
        return True

    def sync(self, bars: list[Bar]) -> None:
        """Catch up with the analyzer (seed or after a gap) in one pass."""
        for bar in bars:
            self.update(bar)

    # --- outputs ----------------------------------------------------------------------------
    def _levels(self, price: float, above: bool) -> tuple[Level, ...]:
        out = []
        for lv in self.levels.nearest(price, above=above, i=self.i)[:LEVELS_SHOWN]:
            out.append(
                Level(
                    price=lv.price,
                    strength=lv.strength(self.i),
                    grade=lv.grade(self.i),
                    kind="resistance" if above else "support",
                )
            )
        return tuple(out)

    def features(self, bar: Bar, snap: AnalysisSnapshot, tick: float) -> Features:
        structure = snap.internal_structure
        events = tuple(
            (e.index, e.type.value, e.direction.value)
            for e in (structure.events if structure else ())
        )
        sweeps = tuple(
            (s.index, s.side.value, s.level)
            for s in (snap.liquidity.sweeps if snap.liquidity else ())
        )
        swing_low = swing_high = None
        if structure is not None:
            for p in reversed(structure.pivots):
                if p.side.value == "low" and swing_low is None:
                    swing_low = p.price
                elif p.side.value == "high" and swing_high is None:
                    swing_high = p.price
                if swing_low is not None and swing_high is not None:
                    break
        return Features(
            index=bar.index,
            time=bar.time,
            close_time=bar.close_time,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            prev_close=self.close_before,
            atr=self.atr.value or 0.0,
            ema20=self.ema20.value,
            ema50=self.ema50.value if self.count >= 50 else None,
            ema200=self.ema200.value if self.count >= 200 else None,
            ema20_prev=self.ema20_prev,
            ema_stack=snap.trend.stack.value if snap.trend else "mixed",
            regime=snap.regime.primary.value if snap.regime else "transitional",
            direction=snap.trend.direction.value if snap.trend else "neutral",
            rsi=self.rsi.value if self.count > 14 else None,
            rsi_slope=self.rsi.slope() if self.count > 14 else None,
            structure_events=events,
            sweeps=sweeps,
            supports=self._levels(bar.close, above=False),
            resistances=self._levels(bar.close, above=True),
            swing_low=swing_low,
            swing_high=swing_high,
            tick=tick,
        )

    def overlay(self, price: float) -> dict[str, Any]:
        """Chart payload: EMA values and the strongest nearby S/R levels with strength."""
        return {
            "ema": {
                "20": self.ema20.value,
                "50": self.ema50.value if self.count >= 50 else None,
                "200": self.ema200.value if self.count >= 200 else None,
            },
            "levels": [
                {"price": lv.price, "strength": lv.strength, "grade": lv.grade, "kind": lv.kind}
                for lv in (*self._levels(price, above=False), *self._levels(price, above=True))
            ],
        }
