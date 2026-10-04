"""Normalized analysis vocabulary. Every value has ONE definition (docs/market-intelligence.md)."""

from __future__ import annotations

from enum import StrEnum


class TrendDirection(StrEnum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class StructureDirection(StrEnum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class DirectionalRegime(StrEnum):
    STRONG_UPTREND = "strong_uptrend"
    UPTREND = "uptrend"
    RANGE = "range"
    DOWNTREND = "downtrend"
    STRONG_DOWNTREND = "strong_downtrend"
    TRANSITIONAL = "transitional"


class VolatilityRegime(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    EXTREME = "extreme"


class MarketRegime(StrEnum):
    """Single dominant label derived from the two orthogonal regimes (never contradictory).

    Volatility labels win only when there is no directional trend (range/transitional)."""

    STRONG_UPTREND = "strong_uptrend"
    UPTREND = "uptrend"
    RANGING = "ranging"
    DOWNTREND = "downtrend"
    STRONG_DOWNTREND = "strong_downtrend"
    HIGH_VOLATILITY = "high_volatility"
    LOW_VOLATILITY = "low_volatility"
    TRANSITIONAL = "transitional"


class StructureLayer(StrEnum):
    SWING = "swing"
    INTERNAL = "internal"


class StructureEventType(StrEnum):
    BOS = "BOS"
    CHOCH = "CHOCH"


class PivotType(StrEnum):
    HH = "HH"
    HL = "HL"
    LH = "LH"
    LL = "LL"
    HIGH = "HIGH"  # first pivot high, or exactly equal to the previous one
    LOW = "LOW"


class PivotSide(StrEnum):
    HIGH = "high"
    LOW = "low"


class FeatureStatus(StrEnum):
    DEVELOPING = "developing"  # depends on the forming candle; may change or disappear
    CONFIRMED = "confirmed"  # fixed at a candle close; never moves or disappears
    INVALIDATED = "invalidated"


class LiquiditySide(StrEnum):
    BUY_SIDE = "buy_side"  # resting above highs (buy stops)
    SELL_SIDE = "sell_side"  # resting below lows (sell stops)


class LiquiditySource(StrEnum):
    EQUAL_HIGHS = "equal_highs"
    EQUAL_LOWS = "equal_lows"
    SWING_HIGH = "swing_high"
    SWING_LOW = "swing_low"


class PoolStatus(StrEnum):
    ACTIVE = "active"
    SWEPT = "swept"  # traded through, closed back inside (liquidity sweep)
    BROKEN = "broken"  # closed beyond (acceptance / breakout), not a sweep
    MERGED = "merged"  # a swing-pivot pool absorbed into an equal-level pool
    EXPIRED = "expired"


class ZoneType(StrEnum):
    BULLISH_FVG = "bullish_fvg"
    BEARISH_FVG = "bearish_fvg"
    BULLISH_OB = "bullish_ob"
    BEARISH_OB = "bearish_ob"
    PREMIUM = "premium"
    DISCOUNT = "discount"
    EQUILIBRIUM = "equilibrium"
    OTE = "ote"


class ZoneStatus(StrEnum):
    ACTIVE = "active"  # untouched (OB) / less than half filled (FVG)
    MITIGATED = "mitigated"  # price returned into the zone; still valid
    INVALIDATED = "invalidated"  # closed through the far side (beyond tolerance)
    EXPIRED = "expired"  # older than the tracking window


class SpreadState(StrEnum):
    EXPANDING = "expanding"
    COMPRESSING = "compressing"
    FLAT = "flat"


class EmaStack(StrEnum):
    BULLISH = "bullish"  # EMA20 > EMA50 > EMA100 > EMA200
    BEARISH = "bearish"
    MIXED = "mixed"


class MtfAlignment(StrEnum):
    STRONG_BULLISH = "strong_bullish"  # execution and every higher timeframe bullish
    BULLISH = "bullish"  # execution bullish, higher timeframes not opposed
    STRONG_BEARISH = "strong_bearish"
    BEARISH = "bearish"
    COUNTERTREND = "countertrend"  # execution opposes the higher-timeframe consensus
    MIXED = "mixed"  # higher timeframes disagree among themselves
    NEUTRAL = "neutral"  # execution has no direction
    UNAVAILABLE = "unavailable"  # no higher timeframe / context not ready


class PremiumDiscountZone(StrEnum):
    PREMIUM = "premium"
    DISCOUNT = "discount"
    EQUILIBRIUM = "equilibrium"
    ABOVE_RANGE = "above_range"
    BELOW_RANGE = "below_range"
