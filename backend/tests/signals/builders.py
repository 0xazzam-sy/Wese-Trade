"""Fully controlled synthetic inputs for signal-engine tests.

Default scene (5m, price 100, ATR 1): bullish swing structure (protected low 95), an
internal bullish BOS confirmed on the evaluated candle (the trigger), bullish trend,
uptrend regime, 15m/1h bullish, equilibrium location, a buy-side pool at 104.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from app.analysis.enums import (
    DirectionalRegime,
    EmaStack,
    FeatureStatus,
    LiquiditySide,
    LiquiditySource,
    MarketRegime,
    MtfAlignment,
    PivotSide,
    PremiumDiscountZone,
    SpreadState,
    StructureDirection,
    StructureEventType,
    StructureLayer,
    TrendDirection,
    VolatilityRegime,
    ZoneStatus,
    ZoneType,
)
from app.analysis.models import (
    AnalysisSnapshot,
    CandleFeatures,
    DevelopingFeatures,
    EmaFeature,
    FairValueGap,
    LiquidityPool,
    LiquidityState,
    LiquiditySweep,
    MomentumFeatures,
    MtfFrame,
    MultiTimeframeContext,
    OrderBlock,
    PremiumDiscount,
    ProtectedLevel,
    RegimeFeatures,
    StructureEvent,
    StructureState,
    TrendFeatures,
    VolatilityFeatures,
    VolumeFeatures,
)
from app.analysis.series import Bar
from app.signal_engine.models import SignalInput


def must[X](value: X | None) -> X:
    """Narrow an optional field in tests (fails loudly instead of using `!`/ignores)."""
    if value is None:
        raise AssertionError("expected a value")
    return value


STEP = 300
T = 1_800_000_000 - (1_800_000_000 % STEP)  # open time of the evaluated (trigger) candle
BULL, BEAR, NEUTRAL = (
    StructureDirection.BULLISH,
    StructureDirection.BEARISH,
    StructureDirection.NEUTRAL,
)


def event(
    layer: str = "internal",
    kind: str = "BOS",
    direction: StructureDirection = BULL,
    *,
    time: int = T,
    level: float = 99.5,
    displacement: float = 70.0,
    relvol: float | None = 1.6,
) -> StructureEvent:
    lay = StructureLayer(layer)
    return StructureEvent(
        id=f"{layer}:{kind}:{direction.value}:{time}",
        layer=lay,
        type=StructureEventType(kind),
        direction=direction,
        level=level,
        level_index=0,
        level_time=time - 10 * STEP,
        index=100,
        time=time,
        confirmed_time=time + STEP,
        close=100.0,
        displacement=displacement,
        relative_volume=relvol,
        volume_confirmed=relvol is not None and relvol >= 1.5,
    )


def protected(side: PivotSide, price: float, layer: str = "swing") -> ProtectedLevel:
    return ProtectedLevel(
        id=f"{layer}:p:{side.value}:{price}",
        layer=StructureLayer(layer),
        side=side,
        price=price,
        index=0,
        time=T - 20 * STEP,
        created_time=T - 15 * STEP,
    )


def structure(
    layer: str,
    direction: StructureDirection,
    events: tuple[StructureEvent, ...] = (),
    *,
    low: float | None = None,
    high: float | None = None,
    break_high: float | None = None,
    break_low: float | None = None,
) -> StructureState:
    return StructureState(
        layer=StructureLayer(layer),
        direction=direction,
        pivots=(),
        events=events,
        last_event=events[-1] if events else None,
        protected_high=protected(PivotSide.HIGH, high, layer) if high is not None else None,
        protected_low=protected(PivotSide.LOW, low, layer) if low is not None else None,
        break_high=break_high,
        break_low=break_low,
    )


def frame(
    tf: str, direction: str = "bullish", regime: str = "uptrend", ready: bool = True
) -> MtfFrame:
    return MtfFrame(
        timeframe=tf,
        ready=ready,
        candle_time=T,
        trend=TrendDirection(direction),
        structure=StructureDirection(direction),
        directional_regime=DirectionalRegime(regime),
        volatility_regime=VolatilityRegime.NORMAL,
    )


def pool(level: float, side: LiquiditySide = LiquiditySide.BUY_SIDE) -> LiquidityPool:
    source = (
        LiquiditySource.SWING_HIGH if side is LiquiditySide.BUY_SIDE else LiquiditySource.SWING_LOW
    )
    return LiquidityPool(f"pool:{level}", side, source, level, 0, T - 50 * STEP, T - 45 * STEP)


def sweep(
    side: LiquiditySide, level: float, extreme: float, *, bars_ago: int = 3, responded: bool = True
) -> LiquiditySweep:
    return LiquiditySweep(
        id=f"sweep:{level}",
        side=side,
        pool_id=f"pool:{level}",
        source=LiquiditySource.SWING_LOW,
        level=level,
        index=90,
        time=T - bars_ago * STEP,
        confirmed_time=T - bars_ago * STEP + STEP,
        extreme=extreme,
        close=level + (0.3 if side is LiquiditySide.SELL_SIDE else -0.3),
        penetration=abs(extreme - level),
        penetration_atr=abs(extreme - level),
        rejection=0.7,
        quality=75.0,
        structure_response="internal:CHOCH:x" if responded else None,
    )


def order_block(kind: ZoneType, top: float, bottom: float, quality: float = 70.0) -> OrderBlock:
    return OrderBlock(
        id=f"ob:{kind.value}:{top}",
        type=kind,
        top=top,
        bottom=bottom,
        index=0,
        time=T - 20 * STEP,
        end_index=0,
        created_index=1,
        confirmed_time=T - 18 * STEP,
        source_event_id="e",
        layer=StructureLayer.SWING,
        displacement=70.0,
        relative_volume=1.5,
        quality=quality,
        status=ZoneStatus.ACTIVE,
    )


def fvg(kind: ZoneType, top: float, bottom: float) -> FairValueGap:
    return FairValueGap(
        id=f"fvg:{kind.value}:{top}",
        type=kind,
        top=top,
        bottom=bottom,
        index=0,
        time=T - 10 * STEP,
        created_index=1,
        confirmed_time=T - 8 * STEP,
        size_atr=1.0,
        displacement=70.0,
        relative_volume=1.4,
        aligned=True,
        quality=70.0,
    )


def candle(
    direction: str = "up", close_location: float = 0.9, patterns: tuple[str, ...] = ("strong_body",)
) -> CandleFeatures:
    return CandleFeatures(
        T, FeatureStatus.CONFIRMED, direction, 0.8, 0.05, 0.15, 1.2, close_location, patterns
    )


def make_snapshot(**overrides: Any) -> AnalysisSnapshot:
    trigger = event()
    snap = AnalysisSnapshot(
        symbol="BTCUSDT",
        timeframe="5m",
        analysis_ready=True,
        reason=None,
        candle_time=T,
        forming_time=None,
        price=100.0,
        generated_at="2000-01-01T00:00:00Z",
        candles_analyzed=999,
        trend=TrendFeatures(
            direction=TrendDirection.BULLISH,
            score=0.7,
            emas=tuple(EmaFeature(p, 99.0 - p / 100, 0.1, 0.1, 1.0) for p in (20, 50, 100, 200)),
            stack=EmaStack.BULLISH,
            alignment_score=3,
            spread_atr=2.0,
            spread_change_atr=0.2,
            spread_state=SpreadState.EXPANDING,
            price_above_ema200=True,
        ),
        regime=RegimeFeatures(
            MarketRegime.UPTREND, DirectionalRegime.UPTREND, VolatilityRegime.NORMAL, {}
        ),
        volatility=VolatilityFeatures(1.0, 1.0, 50.0, 1.2, 0.1, VolatilityRegime.NORMAL),
        momentum=MomentumFeatures(60.0, 1.0, None, False, False, 0.5, 1.0, 0.1, None),
        volume=VolumeFeatures(16.0, 10.0, 1.6, 1.5, 90.0, False, False),
        candle=candle(),
        forming_candle=None,
        swing_structure=structure("swing", BULL, low=95.0, break_high=106.0),
        internal_structure=structure("internal", BULL, (trigger,), low=98.0, break_high=101.5),
        liquidity=LiquidityState((pool(104.0),), (), (), (), 1, 0, 104.0, None),
        fair_value_gaps=(),
        order_blocks=(),
        premium_discount=PremiumDiscount(
            StructureLayer.SWING,
            106.0,
            T - 5 * STEP,
            95.0,
            T - 20 * STEP,
            100.5,
            101.05,
            99.95,
            45.5,
            PremiumDiscountZone.EQUILIBRIUM,
        ),
        ote=None,
        multi_timeframe=MultiTimeframeContext(
            frame("5m"),
            (frame("15m"), frame("1h")),
            MtfAlignment.STRONG_BULLISH,
            MtfAlignment.STRONG_BULLISH,
            True,
            MtfAlignment.STRONG_BULLISH,
        ),
        developing=DevelopingFeatures(),
    )
    return replace(snap, **overrides)


def bars(closes: list[float] | None = None, wick: float = 0.3) -> tuple[Bar, ...]:
    closes = closes or [95 + i * 5 / 29 for i in range(30)]
    out = []
    prev = closes[0]
    for i, c in enumerate(closes):
        t = T - (len(closes) - 1 - i) * STEP
        out.append(Bar(i, t, t + STEP, prev, max(prev, c) + wick, min(prev, c) - wick, c, 10.0))
        prev = c
    return tuple(out)


def make_input(snapshot: AnalysisSnapshot | None = None, **kwargs: Any) -> SignalInput:
    return SignalInput(
        snapshot=snapshot or make_snapshot(),
        recent_bars=kwargs.pop("recent_bars", bars()),
        tick_size=0.01,
        **kwargs,
    )
