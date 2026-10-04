"""Central analysis configuration. Every tunable lives here — no magic numbers in modules.

Defaults were sanity-checked on real OKX data for BTC/ETH/SOL on 1m/5m/15m/1h
(feature density: docs/market-intelligence.md §20). They are NOT optimized for profit.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.market_data.timeframes import Timeframe


@dataclass(frozen=True, slots=True)
class AnalysisConfig:
    # --- trend / EMA ---------------------------------------------------------
    ema_periods: tuple[int, ...] = (20, 50, 100, 200)
    ema_slope_lookback: int = 5  # bars used for EMA slope
    ema_spread_lookback: int = 5  # bars used for EMA20-EMA200 spread change
    ema_spread_flat_atr: float = 0.15  # |spread change| below this (ATR units) is "flat"
    trend_slope_full_scale: float = 0.15  # EMA50 slope (ATR/bar) mapped to a full ±1 score
    trend_threshold: float = 0.25  # |trend score| at/above this gives a direction
    trend_min_slope: float = 0.02  # |EMA50 slope| (ATR/bar) below this counts as flat

    # --- volatility ------------------------------------------------------------
    atr_period: int = 14
    atr_percentile_window: int = 100
    realized_vol_window: int = 20
    vol_low_percentile: float = 20.0
    vol_high_percentile: float = 80.0
    vol_extreme_percentile: float = 95.0

    # --- momentum ------------------------------------------------------------
    rsi_period: int = 14
    rsi_slope_lookback: int = 3
    rsi_overbought: float = 70.0
    rsi_oversold: float = 30.0
    roc_period: int = 10
    accel_period: int = 5
    divergence_lookback_pivots: int = 2  # compare the last two internal pivots

    # --- volume --------------------------------------------------------------
    volume_lookback: int = 20
    volume_percentile_window: int = 100
    volume_spike_ratio: float = 2.0
    volume_contraction_ratio: float = 0.5
    breakout_volume_ratio: float = 1.5

    # --- regime --------------------------------------------------------------
    efficiency_window: int = 20
    strong_trend_score: float = 0.6
    strong_trend_efficiency: float = 0.35
    range_efficiency: float = 0.3
    range_compression_short: int = 20
    range_compression_long: int = 100

    # --- pivots / structure ----------------------------------------------------
    swing_left: int = 5
    swing_right: int = 5  # swing pivots confirm 5 candles after the pivot candle
    internal_left: int = 2
    internal_right: int = 2  # internal pivots confirm 2 candles after the pivot candle
    max_pivots_kept: int = 400

    # --- displacement ------------------------------------------------------------
    displacement_range_full_atr: float = 2.0  # candle range = 2 ATR scores full marks
    displacement_volume_full: float = 1.5  # relative volume 1 + this scores full marks
    displacement_move_full_atr: float = 1.0  # close 1 ATR beyond the level scores full

    # --- liquidity -----------------------------------------------------------
    equal_level_atr: float = 0.1  # EQH/EQL tolerance = max(0.1 ATR, 2 ticks)
    equal_level_min_ticks: int = 2
    equal_level_lookback: int = 150  # bars a pivot can wait for its equal partner
    pool_max_age: int = 500  # bars an untouched pool is tracked
    sweep_response_bars: int = 10  # bars after a sweep in which a structure response is noted

    # --- fair value gaps -----------------------------------------------------------
    fvg_min_atr: float = 0.35  # minimum gap size, ATR units
    fvg_min_ticks: int = 2
    fvg_mitigated_fill: float = 0.5  # filled to the midpoint (consequent encroachment)
    fvg_max_age: int = 500

    # --- order blocks ----------------------------------------------------------------
    ob_search_bars: int = 5  # bars before the leg extreme searched for the opposite candle
    ob_max_cluster: int = 3  # consecutive opposite candles merged into one block
    ob_min_displacement: float = 50.0  # required displacement score (0-100) of the leg
    ob_invalidation_atr: float = 0.1  # close beyond the far edge by this much invalidates
    ob_invalidation_min_ticks: int = 2
    ob_max_age: int = 500

    # --- premium / discount / OTE ---------------------------------------------------------
    equilibrium_band: float = 0.05  # 45%-55% of the range is "equilibrium"
    ote_start: float = 0.618
    ote_focus: float = 0.705
    ote_end: float = 0.79

    # --- readiness / output ----------------------------------------------------------
    min_candles: int = 300  # EMA200 + warm-up for ATR percentiles and structure
    history_rows: int = 300  # compact per-candle feature rows kept for /history
    max_bars_kept: int = 3000
    output_pivots: int = 30
    output_events: int = 20
    output_pools: int = 16
    output_equal_levels: int = 12
    output_sweeps: int = 10
    output_zones: int = 12


DEFAULT_CONFIG = AnalysisConfig()

# Higher-timeframe context per execution timeframe. 4h does not exist yet and is never
# fabricated: 1h has no higher context for now.
MTF_CONTEXT: dict[Timeframe, tuple[Timeframe, ...]] = {
    Timeframe.M1: (Timeframe.M5, Timeframe.M15),
    Timeframe.M5: (Timeframe.M15, Timeframe.H1),
    Timeframe.M10: (Timeframe.M30, Timeframe.H1),
    Timeframe.M15: (Timeframe.M30, Timeframe.H1),
    Timeframe.M30: (Timeframe.H1,),
    Timeframe.H1: (),
}
