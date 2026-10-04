"""Liquidity sweep vs breakout — one deterministic definition.

For an ACTIVE buy-side pool at level L and tolerance t = max(equal_level_atr * ATR,
equal_level_min_ticks * tick), a closed candle with high > L + t is:
  * a LIQUIDITY SWEEP if it closes back at/below L (traded beyond, rejected), or
  * a BREAKOUT (pool "broken") if it closes above L (acceptance beyond the level).
Sell-side pools mirror this. A breakout is never reported as a sweep. A poke within the
tolerance (high in (L, L + t]) is an equal touch, not a sweep — the same tolerance that
defines equal highs/lows.
"""

from __future__ import annotations

from app.analysis.enums import LiquiditySide
from app.analysis.models import DevelopingSweep, LiquidityPool, LiquiditySweep
from app.analysis.scoring.feature_quality import sweep_quality
from app.analysis.series import Bar


def pierced(pool: LiquidityPool, bar: Bar, margin: float = 0.0) -> bool:
    if pool.side is LiquiditySide.BUY_SIDE:
        return bar.high > pool.level + margin
    return bar.low < pool.level - margin


def closed_back_inside(pool: LiquidityPool, close: float) -> bool:
    if pool.side is LiquiditySide.BUY_SIDE:
        return close <= pool.level
    return close >= pool.level


def make_sweep(
    pool: LiquidityPool, bar: Bar, atr: float | None, relative_volume: float | None
) -> LiquiditySweep:
    buy = pool.side is LiquiditySide.BUY_SIDE
    extreme = bar.high if buy else bar.low
    penetration = abs(extreme - pool.level)
    inside = (pool.level - bar.close) if buy else (bar.close - pool.level)
    rejection = (
        ((bar.high - bar.close) if buy else (bar.close - bar.low)) / bar.range
        if bar.range > 0
        else 0.0
    )
    pen_atr = penetration / atr if atr else None
    inside_atr = inside / atr if atr else None
    return LiquiditySweep(
        id=f"sweep:{pool.id}:{bar.time}",
        side=pool.side,
        pool_id=pool.id,
        source=pool.source,
        level=pool.level,
        index=bar.index,
        time=bar.time,
        confirmed_time=bar.close_time,
        extreme=extreme,
        close=bar.close,
        penetration=penetration,
        penetration_atr=pen_atr,
        rejection=rejection,
        quality=sweep_quality(rejection, inside_atr, pen_atr, pool.touches, relative_volume),
    )


def developing_sweep(
    pool: LiquidityPool, forming: Bar, margin: float = 0.0
) -> DevelopingSweep | None:
    if not pierced(pool, forming, margin) or not closed_back_inside(pool, forming.close):
        return None
    buy = pool.side is LiquiditySide.BUY_SIDE
    return DevelopingSweep(
        side=pool.side,
        pool_id=pool.id,
        level=pool.level,
        extreme=forming.high if buy else forming.low,
        price=forming.close,
    )
