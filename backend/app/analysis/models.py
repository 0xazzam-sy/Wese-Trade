"""Typed analysis models.

Conventions:
- Times are UTC epoch SECONDS (the chart's native unit). `time` is the open time of the
  candle a feature is anchored to; `confirmed_time` is the CLOSE time of the candle at
  which the feature became known (never earlier than the data that defines it).
- Prices/levels are float64. Analysis values are features, never order prices.
- `index` fields are absolute bar indices within the analyzer's stream (0 = first candle
  the analyzer saw); they are stable for the analyzer's lifetime.
- Frozen models are immutable facts. Mutable models (zones, pools) only move FORWARD in
  their lifecycle (active -> mitigated -> invalidated); their defining fields never change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
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
    PivotType,
    PoolStatus,
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


# --- structure -----------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Pivot:
    id: str
    layer: StructureLayer
    side: PivotSide
    type: PivotType
    price: float
    index: int
    time: int
    confirmed_index: int
    confirmed_time: int
    status: FeatureStatus = FeatureStatus.CONFIRMED


@dataclass(frozen=True, slots=True)
class StructureEvent:
    id: str
    layer: StructureLayer
    type: StructureEventType
    direction: StructureDirection  # direction of the break (bullish = broke upward)
    level: float  # broken price level
    level_index: int
    level_time: int
    index: int  # break candle
    time: int
    confirmed_time: int
    close: float
    displacement: float  # 0-100 strength of the break candle; NOT a confidence
    relative_volume: float | None
    volume_confirmed: bool
    status: FeatureStatus = FeatureStatus.CONFIRMED


@dataclass(slots=True)
class ProtectedLevel:
    id: str
    layer: StructureLayer
    side: PivotSide  # LOW protects bullish structure, HIGH protects bearish structure
    price: float
    index: int
    time: int
    created_time: int  # close time of the structure break that defined it
    status: str = "active"  # active | superseded | broken
    ended_time: int | None = None

    @property
    def active(self) -> bool:
        return self.status == "active"


@dataclass(frozen=True, slots=True)
class DevelopingBreak:
    """A break that holds only with the forming candle's current price."""

    layer: StructureLayer
    type: StructureEventType
    direction: StructureDirection
    level: float
    price: float
    status: FeatureStatus = FeatureStatus.DEVELOPING


@dataclass(frozen=True, slots=True)
class StructureState:
    layer: StructureLayer
    direction: StructureDirection
    pivots: tuple[Pivot, ...]
    events: tuple[StructureEvent, ...]
    last_event: StructureEvent | None
    protected_high: ProtectedLevel | None
    protected_low: ProtectedLevel | None
    break_high: float | None  # level a bullish BOS/CHoCH must close above
    break_low: float | None


# --- liquidity -----------------------------------------------------------------------
@dataclass(slots=True)
class EqualLevel:
    id: str
    side: LiquiditySide
    level: float
    tolerance: float
    touches: int
    first_index: int
    first_time: int
    last_index: int
    last_time: int
    confirmed_time: int
    strength: float = 0.0
    status: PoolStatus = PoolStatus.ACTIVE
    ended_time: int | None = None

    @property
    def active(self) -> bool:
        return self.status is PoolStatus.ACTIVE


@dataclass(slots=True)
class LiquidityPool:
    id: str
    side: LiquiditySide
    source: LiquiditySource
    level: float
    index: int
    time: int
    confirmed_time: int
    touches: int = 1
    status: PoolStatus = PoolStatus.ACTIVE
    ended_index: int | None = None
    ended_time: int | None = None


@dataclass(slots=True)
class LiquiditySweep:
    id: str
    side: LiquiditySide
    pool_id: str
    source: LiquiditySource
    level: float
    index: int
    time: int
    confirmed_time: int
    extreme: float  # wick extreme beyond the level
    close: float
    penetration: float
    penetration_atr: float | None
    rejection: float  # wick beyond-level share of the candle range (0-1)
    quality: float
    status: FeatureStatus = FeatureStatus.CONFIRMED
    structure_response: str | None = None  # id of a later opposite structure event
    response_time: int | None = None


@dataclass(frozen=True, slots=True)
class DevelopingSweep:
    side: LiquiditySide
    pool_id: str
    level: float
    extreme: float
    price: float
    status: FeatureStatus = FeatureStatus.DEVELOPING


@dataclass(frozen=True, slots=True)
class LiquidityState:
    pools: tuple[LiquidityPool, ...]
    equal_highs: tuple[EqualLevel, ...]
    equal_lows: tuple[EqualLevel, ...]
    sweeps: tuple[LiquiditySweep, ...]
    active_buy_side: int
    active_sell_side: int
    nearest_buy_side: float | None
    nearest_sell_side: float | None


# --- zones ----------------------------------------------------------------------
@dataclass(slots=True)
class FairValueGap:
    id: str
    type: ZoneType
    top: float
    bottom: float
    index: int  # middle (displacement) candle
    time: int
    created_index: int  # third candle; the gap is known at its close
    confirmed_time: int
    size_atr: float
    displacement: float
    relative_volume: float | None
    aligned: bool  # with internal structure direction at creation
    quality: float = 0.0
    filled: float = 0.0  # 0-1 share of the gap traded into
    status: ZoneStatus = ZoneStatus.ACTIVE
    mitigated_time: int | None = None
    ended_time: int | None = None
    status_detail: FeatureStatus = FeatureStatus.CONFIRMED

    @property
    def mid(self) -> float:
        return (self.top + self.bottom) / 2

    @property
    def size(self) -> float:
        return self.top - self.bottom


@dataclass(slots=True)
class OrderBlock:
    id: str
    type: ZoneType
    top: float
    bottom: float
    index: int  # first candle of the block
    time: int
    end_index: int
    created_index: int  # the structure-break candle
    confirmed_time: int
    source_event_id: str
    layer: StructureLayer
    displacement: float
    relative_volume: float | None
    quality: float = 0.0
    touches: int = 0
    status: ZoneStatus = ZoneStatus.ACTIVE
    mitigated_time: int | None = None
    ended_time: int | None = None
    inside: bool = False

    @property
    def mid(self) -> float:
        return (self.top + self.bottom) / 2

    @property
    def active(self) -> bool:
        return self.status in (ZoneStatus.ACTIVE, ZoneStatus.MITIGATED)


@dataclass(frozen=True, slots=True)
class PremiumDiscount:
    layer: StructureLayer
    high: float
    high_time: int
    low: float
    low_time: int
    equilibrium: float
    equilibrium_upper: float
    equilibrium_lower: float
    position: float  # current price as % of the range (0 = low, 100 = high)
    zone: PremiumDiscountZone


@dataclass(frozen=True, slots=True)
class OteZone:
    direction: StructureDirection  # bullish = retracement down into a bullish impulse
    layer: StructureLayer
    impulse_start: float
    impulse_start_time: int
    impulse_end: float
    impulse_end_time: int
    upper: float
    lower: float
    focus: float
    active: bool
    price_in_zone: bool


# --- indicators -----------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class EmaFeature:
    period: int
    value: float
    slope: float  # price units per bar
    normalized_slope: float | None  # ATR units per bar
    distance_atr: float | None  # (close - EMA) / ATR


@dataclass(frozen=True, slots=True)
class TrendFeatures:
    direction: TrendDirection
    score: float  # -1..1 composite (stack, EMA50 slope, position); a feature, not a signal
    emas: tuple[EmaFeature, ...]
    stack: EmaStack
    alignment_score: int  # -3..3 correctly ordered adjacent EMA pairs
    spread_atr: float | None  # (EMA20 - EMA200) / ATR
    spread_change_atr: float | None
    spread_state: SpreadState
    price_above_ema200: bool | None


@dataclass(frozen=True, slots=True)
class VolatilityFeatures:
    atr: float
    atr_pct: float
    atr_percentile: float | None
    range_atr: float | None
    realized_vol: float | None  # stdev of log returns (%) over the window
    regime: VolatilityRegime


@dataclass(frozen=True, slots=True)
class MomentumFeatures:
    rsi: float | None
    rsi_slope: float | None
    rsi_cross_50: str | None  # "up" | "down" on the last closed candle
    rsi_overbought: bool
    rsi_oversold: bool
    roc: float | None  # % change over roc_period
    impulse_atr: float | None  # same move in ATR units
    acceleration: float | None  # ROC(accel) now minus ROC(accel) accel bars ago
    divergence: str | None  # "bullish" | "bearish" (internal pivots vs RSI); a hook only


@dataclass(frozen=True, slots=True)
class VolumeFeatures:
    volume: float
    average: float | None
    relative: float | None
    zscore: float | None
    percentile: float | None
    spike: bool
    contraction: bool


@dataclass(frozen=True, slots=True)
class RegimeFeatures:
    primary: MarketRegime
    directional: DirectionalRegime
    volatility: VolatilityRegime
    inputs: dict[str, Any]


@dataclass(frozen=True, slots=True)
class CandleFeatures:
    time: int
    status: FeatureStatus
    direction: str  # up | down | flat
    body_pct: float
    upper_wick_pct: float
    lower_wick_pct: float
    range_atr: float | None
    close_location: float  # 0 = closed at the low, 1 = at the high
    patterns: tuple[str, ...]


# --- multi-timeframe ---------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class MtfFrame:
    timeframe: str
    ready: bool
    candle_time: int | None
    trend: TrendDirection | None
    structure: StructureDirection | None
    directional_regime: DirectionalRegime | None
    volatility_regime: VolatilityRegime | None


@dataclass(frozen=True, slots=True)
class MultiTimeframeContext:
    execution: MtfFrame
    higher: tuple[MtfFrame, ...]
    directional_alignment: MtfAlignment
    structure_alignment: MtfAlignment
    volatility_aligned: bool | None
    regime_alignment: MtfAlignment


@dataclass(frozen=True, slots=True)
class DevelopingFeatures:
    """Everything that depends on the FORMING candle. May change or vanish until close."""

    swing_pivots: tuple[Pivot, ...] = ()
    internal_pivots: tuple[Pivot, ...] = ()
    swing_breaks: tuple[DevelopingBreak, ...] = ()
    internal_breaks: tuple[DevelopingBreak, ...] = ()
    sweeps: tuple[DevelopingSweep, ...] = ()
    fair_value_gaps: tuple[FairValueGap, ...] = ()


# --- snapshot -------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class AnalysisSnapshot:
    symbol: str
    timeframe: str
    analysis_ready: bool
    reason: str | None  # why not ready
    candle_time: int | None  # open time of the last CLOSED candle analyzed
    forming_time: int | None
    price: float | None  # forming close (or last close)
    generated_at: str  # UTC ISO-8601
    candles_analyzed: int
    trend: TrendFeatures | None = None
    regime: RegimeFeatures | None = None
    volatility: VolatilityFeatures | None = None
    momentum: MomentumFeatures | None = None
    volume: VolumeFeatures | None = None
    candle: CandleFeatures | None = None
    forming_candle: CandleFeatures | None = None
    swing_structure: StructureState | None = None
    internal_structure: StructureState | None = None
    liquidity: LiquidityState | None = None
    fair_value_gaps: tuple[FairValueGap, ...] = ()
    order_blocks: tuple[OrderBlock, ...] = ()
    premium_discount: PremiumDiscount | None = None
    ote: OteZone | None = None
    multi_timeframe: MultiTimeframeContext | None = None
    developing: DevelopingFeatures | None = None
    counts: dict[str, int] = field(default_factory=dict)
    debug: dict[str, Any] | None = None
