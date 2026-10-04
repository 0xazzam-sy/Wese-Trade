"""Equal highs / equal lows (EQH / EQL).

Two or more confirmed INTERNAL pivots on the same side whose prices differ by at most
`tolerance = max(equal_level_atr * ATR, equal_level_min_ticks * tick_size)` form an equal
level, provided price never traded beyond the earlier pivot (by more than the tolerance)
in between. Further pivots within tolerance add touches. The level is the most extreme
touch (highest high for EQH, lowest low for EQL) — where the resting liquidity sits.
"""

from __future__ import annotations

from app.analysis.config import AnalysisConfig
from app.analysis.enums import LiquiditySide, PivotSide
from app.analysis.models import EqualLevel, Pivot
from app.analysis.scoring.feature_quality import equal_level_strength
from app.analysis.series import Bar


def tolerance(config: AnalysisConfig, atr: float | None, tick: float) -> float:
    by_atr = config.equal_level_atr * atr if atr else 0.0
    return max(by_atr, config.equal_level_min_ticks * tick)


class EqualLevelDetector:
    def __init__(self, config: AnalysisConfig, tick: float) -> None:
        self.config = config
        self.tick = tick
        self._candidates: dict[PivotSide, list[tuple[Pivot, float]]] = {
            PivotSide.HIGH: [],
            PivotSide.LOW: [],
        }

    def on_bar(self, bar: Bar) -> None:
        """Drop candidates that price has already traded through (beyond tolerance)."""
        lookback = self.config.equal_level_lookback
        self._candidates[PivotSide.HIGH] = [
            (p, tol)
            for p, tol in self._candidates[PivotSide.HIGH]
            if bar.high <= p.price + tol and bar.index - p.index <= lookback
        ]
        self._candidates[PivotSide.LOW] = [
            (p, tol)
            for p, tol in self._candidates[PivotSide.LOW]
            if bar.low >= p.price - tol and bar.index - p.index <= lookback
        ]

    def on_pivot(
        self, pivot: Pivot, atr: float | None, active: list[EqualLevel]
    ) -> tuple[EqualLevel | None, bool]:
        """Returns (level, is_new). Extends an active level or pairs with a candidate."""
        tol = tolerance(self.config, atr, self.tick)
        side = LiquiditySide.BUY_SIDE if pivot.side is PivotSide.HIGH else LiquiditySide.SELL_SIDE
        candidates = self._candidates[pivot.side]
        result: tuple[EqualLevel | None, bool] = (None, False)
        for level in active:
            if level.side is side and abs(level.level - pivot.price) <= level.tolerance:
                level.touches += 1
                level.last_index, level.last_time = pivot.index, pivot.time
                level.confirmed_time = pivot.confirmed_time
                if side is LiquiditySide.BUY_SIDE:
                    level.level = max(level.level, pivot.price)
                else:
                    level.level = min(level.level, pivot.price)
                level.strength = equal_level_strength(level.touches, 0.0, level.tolerance)
                result = (level, False)
                break
        else:
            for prior, prior_tol in reversed(candidates):
                limit = max(tol, prior_tol)
                spread = abs(prior.price - pivot.price)
                if prior.index < pivot.index and spread <= limit:
                    extreme = (
                        max(prior.price, pivot.price)
                        if side is LiquiditySide.BUY_SIDE
                        else min(prior.price, pivot.price)
                    )
                    kind = "eqh" if side is LiquiditySide.BUY_SIDE else "eql"
                    result = (
                        EqualLevel(
                            id=f"{kind}:{prior.time}:{pivot.time}",
                            side=side,
                            level=extreme,
                            tolerance=limit,
                            touches=2,
                            first_index=prior.index,
                            first_time=prior.time,
                            last_index=pivot.index,
                            last_time=pivot.time,
                            confirmed_time=pivot.confirmed_time,
                            strength=equal_level_strength(2, spread, limit),
                        ),
                        True,
                    )
                    break
        candidates.append((pivot, tol))
        return result
