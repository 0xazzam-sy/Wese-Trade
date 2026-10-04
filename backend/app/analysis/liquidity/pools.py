"""Liquidity pools: resting liquidity above highs (buy-side) and below lows (sell-side).

Sources: equal highs/lows (internal pivots, see equal_levels.py) and confirmed SWING
pivots. A swing pivot within tolerance of an active pool on the same side adds a touch
instead of a new pool; a new equal level absorbs ("merges") an overlapping swing pool.
Lifecycle per closed candle: active -> swept | broken | expired (forward only).
"""

from __future__ import annotations

from app.analysis.config import AnalysisConfig
from app.analysis.enums import (
    LiquiditySide,
    LiquiditySource,
    PivotSide,
    PoolStatus,
    StructureDirection,
)
from app.analysis.liquidity.equal_levels import EqualLevelDetector, tolerance
from app.analysis.liquidity.sweeps import (
    closed_back_inside,
    developing_sweep,
    make_sweep,
    pierced,
)
from app.analysis.models import (
    DevelopingSweep,
    EqualLevel,
    LiquidityPool,
    LiquidityState,
    LiquiditySweep,
    Pivot,
    StructureEvent,
)
from app.analysis.series import Bar

KEEP_ENDED_BARS = 300


class LiquidityTracker:
    def __init__(self, config: AnalysisConfig, tick: float) -> None:
        self.config = config
        self.tick = tick
        self.equal = EqualLevelDetector(config, tick)
        self.pools: list[LiquidityPool] = []
        self.equal_levels: list[EqualLevel] = []
        self.sweeps: list[LiquiditySweep] = []
        self.counts = {"eqh": 0, "eql": 0, "sweeps": 0, "pools": 0, "breakouts": 0}
        self._margin = 0.0  # pierce margin = equal-level tolerance at the latest candle

    def _active(self) -> list[LiquidityPool]:
        return [p for p in self.pools if p.status is PoolStatus.ACTIVE]

    def _equal(self, pool_id: str) -> EqualLevel | None:
        return next((e for e in self.equal_levels if e.id == pool_id), None)

    def _end(self, pool: LiquidityPool, status: PoolStatus, bar: Bar) -> None:
        pool.status = status
        pool.ended_index, pool.ended_time = bar.index, bar.close_time
        level = self._equal(pool.id)
        if level is not None and level.status is PoolStatus.ACTIVE:
            level.status, level.ended_time = status, bar.close_time

    # --- per closed bar ----------------------------------------------------------------
    def on_bar(
        self, bar: Bar, atr: float | None, relative_volume: float | None
    ) -> list[LiquiditySweep]:
        self.equal.on_bar(bar)
        self._margin = tolerance(self.config, atr, self.tick)
        found: list[LiquiditySweep] = []
        for pool in self._active():
            if bar.index - pool.index > self.config.pool_max_age:
                self._end(pool, PoolStatus.EXPIRED, bar)
            elif pierced(pool, bar, self._margin):
                if closed_back_inside(pool, bar.close):
                    sweep = make_sweep(pool, bar, atr, relative_volume)
                    found.append(sweep)
                    self._end(pool, PoolStatus.SWEPT, bar)
                else:
                    self._end(pool, PoolStatus.BROKEN, bar)
                    self.counts["breakouts"] += 1
        self.sweeps.extend(found)
        self.counts["sweeps"] += len(found)
        cutoff = bar.index - KEEP_ENDED_BARS
        self.pools = [
            p for p in self.pools if p.status is PoolStatus.ACTIVE or (p.ended_index or 0) > cutoff
        ]
        self.equal_levels = [
            e for e in self.equal_levels if e.status is PoolStatus.ACTIVE or e.last_index > cutoff
        ]
        if len(self.sweeps) > 100:
            del self.sweeps[:-100]
        return found

    # --- pool creation -------------------------------------------------------------------
    def on_internal_pivot(self, pivot: Pivot, atr: float | None) -> None:
        active_levels = [e for e in self.equal_levels if e.status is PoolStatus.ACTIVE]
        level, is_new = self.equal.on_pivot(pivot, atr, active_levels)
        if level is None:
            return
        if not is_new:
            pool = next((p for p in self.pools if p.id == level.id), None)
            if pool is not None:
                pool.level, pool.touches = level.level, level.touches
            return
        self.equal_levels.append(level)
        buy = level.side is LiquiditySide.BUY_SIDE
        self.counts["eqh" if buy else "eql"] += 1
        for pool in self._active():
            if pool.side is level.side and abs(pool.level - level.level) <= level.tolerance:
                pool.status = PoolStatus.MERGED  # absorbed; not ended by price
        self._add(
            LiquidityPool(
                id=level.id,
                side=level.side,
                source=LiquiditySource.EQUAL_HIGHS if buy else LiquiditySource.EQUAL_LOWS,
                level=level.level,
                index=level.first_index,
                time=level.first_time,
                confirmed_time=level.confirmed_time,
                touches=level.touches,
            )
        )

    def on_swing_pivot(self, pivot: Pivot, atr: float | None) -> None:
        high = pivot.side is PivotSide.HIGH
        side = LiquiditySide.BUY_SIDE if high else LiquiditySide.SELL_SIDE
        tol = tolerance(self.config, atr, self.tick)
        for pool in self._active():
            if pool.side is side and abs(pool.level - pivot.price) <= tol:
                pool.touches += 1
                return
        self._add(
            LiquidityPool(
                id=f"pool:{side.value}:{pivot.time}",
                side=side,
                source=LiquiditySource.SWING_HIGH if high else LiquiditySource.SWING_LOW,
                level=pivot.price,
                index=pivot.index,
                time=pivot.time,
                confirmed_time=pivot.confirmed_time,
            )
        )

    def _add(self, pool: LiquidityPool) -> None:
        self.pools.append(pool)
        self.counts["pools"] += 1

    def note_structure(self, events: list[StructureEvent]) -> None:
        """Annotate recent sweeps with a later OPPOSITE structure event (forward-only)."""
        for event in events:
            for sweep in self.sweeps:
                if sweep.structure_response is not None:
                    continue
                if not 0 < event.index - sweep.index <= self.config.sweep_response_bars:
                    continue
                wanted = (
                    StructureDirection.BEARISH
                    if sweep.side is LiquiditySide.BUY_SIDE
                    else StructureDirection.BULLISH
                )
                if event.direction is wanted:
                    sweep.structure_response = event.id
                    sweep.response_time = event.confirmed_time

    # --- read-only views ----------------------------------------------------------------
    def developing(self, forming: Bar) -> list[DevelopingSweep]:
        found = (developing_sweep(p, forming, self._margin) for p in self._active())
        return [s for s in found if s is not None]

    def state(self, price: float) -> LiquidityState:
        cfg = self.config
        active = self._active()
        above = [p.level for p in active if p.side is LiquiditySide.BUY_SIDE and p.level >= price]
        below = [p.level for p in active if p.side is LiquiditySide.SELL_SIDE and p.level <= price]
        shown = sorted(active, key=lambda p: abs(p.level - price))[: cfg.output_pools]
        ended = [p for p in self.pools if p.status in (PoolStatus.SWEPT, PoolStatus.BROKEN)]
        shown += ended[-6:]
        levels = self.equal_levels[-cfg.output_equal_levels :]
        return LiquidityState(
            pools=tuple(sorted(shown, key=lambda p: p.time)),
            equal_highs=tuple(e for e in levels if e.side is LiquiditySide.BUY_SIDE),
            equal_lows=tuple(e for e in levels if e.side is LiquiditySide.SELL_SIDE),
            sweeps=tuple(self.sweeps[-cfg.output_sweeps :]),
            active_buy_side=sum(1 for p in active if p.side is LiquiditySide.BUY_SIDE),
            active_sell_side=sum(1 for p in active if p.side is LiquiditySide.SELL_SIDE),
            nearest_buy_side=min(above) if above else None,
            nearest_sell_side=max(below) if below else None,
        )
