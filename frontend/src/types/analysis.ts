/**
 * Wire types for `analysis.update` / GET /analysis/{symbol} (backend app.analysis).
 * Analysis only: there are deliberately no signal, entry, stop or target fields.
 * Times are UTC epoch seconds; prices are numbers (analysis features, not order prices).
 */

export type Direction3 = 'bullish' | 'bearish' | 'neutral';
export type Layer = 'swing' | 'internal';
export type FeatureStatus = 'developing' | 'confirmed' | 'invalidated';
export type ZoneStatus = 'active' | 'mitigated' | 'invalidated' | 'expired';
export type DirectionalRegime =
  'strong_uptrend' | 'uptrend' | 'range' | 'downtrend' | 'strong_downtrend' | 'transitional';
export type VolatilityRegime = 'low' | 'normal' | 'high' | 'extreme';
export type MarketRegime =
  | 'strong_uptrend'
  | 'uptrend'
  | 'ranging'
  | 'downtrend'
  | 'strong_downtrend'
  | 'high_volatility'
  | 'low_volatility'
  | 'transitional';
export type MtfAlignment =
  | 'strong_bullish'
  | 'bullish'
  | 'strong_bearish'
  | 'bearish'
  | 'countertrend'
  | 'mixed'
  | 'neutral'
  | 'unavailable';
export type LiquiditySide = 'buy_side' | 'sell_side';

export interface Pivot {
  id: string;
  layer: Layer;
  side: 'high' | 'low';
  type: 'HH' | 'HL' | 'LH' | 'LL' | 'HIGH' | 'LOW';
  price: number;
  index: number;
  time: number;
  confirmed_index: number;
  confirmed_time: number;
  status: FeatureStatus;
}

export interface StructureEvent {
  id: string;
  layer: Layer;
  type: 'BOS' | 'CHOCH';
  direction: 'bullish' | 'bearish';
  level: number;
  level_index: number;
  level_time: number;
  index: number;
  time: number;
  confirmed_time: number;
  close: number;
  displacement: number;
  relative_volume: number | null;
  volume_confirmed: boolean;
  status: FeatureStatus;
}

export interface ProtectedLevel {
  id: string;
  layer: Layer;
  side: 'high' | 'low';
  price: number;
  index: number;
  time: number;
  created_time: number;
  status: 'active' | 'superseded' | 'broken';
  ended_time: number | null;
  active: boolean;
}

export interface StructureState {
  layer: Layer;
  direction: Direction3;
  pivots: Pivot[];
  events: StructureEvent[];
  last_event: StructureEvent | null;
  protected_high: ProtectedLevel | null;
  protected_low: ProtectedLevel | null;
  break_high: number | null;
  break_low: number | null;
}

export interface DevelopingBreak {
  layer: Layer;
  type: 'BOS' | 'CHOCH';
  direction: 'bullish' | 'bearish';
  level: number;
  price: number;
  status: 'developing';
}

export interface LiquidityPool {
  id: string;
  side: LiquiditySide;
  source: 'equal_highs' | 'equal_lows' | 'swing_high' | 'swing_low';
  level: number;
  index: number;
  time: number;
  confirmed_time: number;
  touches: number;
  status: 'active' | 'swept' | 'broken' | 'merged' | 'expired';
  ended_index: number | null;
  ended_time: number | null;
}

export interface EqualLevel {
  id: string;
  side: LiquiditySide;
  level: number;
  tolerance: number;
  touches: number;
  first_time: number;
  last_time: number;
  confirmed_time: number;
  strength: number;
  status: LiquidityPool['status'];
  ended_time: number | null;
}

export interface LiquiditySweep {
  id: string;
  side: LiquiditySide;
  pool_id: string;
  source: LiquidityPool['source'];
  level: number;
  index: number;
  time: number;
  confirmed_time: number;
  extreme: number;
  close: number;
  penetration: number;
  penetration_atr: number | null;
  rejection: number;
  quality: number;
  status: FeatureStatus;
  structure_response: string | null;
  response_time: number | null;
}

export interface DevelopingSweep {
  side: LiquiditySide;
  pool_id: string;
  level: number;
  extreme: number;
  price: number;
  status: 'developing';
}

export interface LiquidityState {
  pools: LiquidityPool[];
  equal_highs: EqualLevel[];
  equal_lows: EqualLevel[];
  sweeps: LiquiditySweep[];
  active_buy_side: number;
  active_sell_side: number;
  nearest_buy_side: number | null;
  nearest_sell_side: number | null;
}

export interface FairValueGap {
  id: string;
  type: 'bullish_fvg' | 'bearish_fvg';
  top: number;
  bottom: number;
  mid: number;
  size: number;
  index: number;
  time: number;
  created_index: number;
  confirmed_time: number;
  size_atr: number;
  displacement: number;
  quality: number;
  filled: number;
  status: ZoneStatus;
  status_detail: FeatureStatus;
  mitigated_time: number | null;
  ended_time: number | null;
}

export interface OrderBlock {
  id: string;
  type: 'bullish_ob' | 'bearish_ob';
  top: number;
  bottom: number;
  mid: number;
  index: number;
  time: number;
  created_index: number;
  confirmed_time: number;
  source_event_id: string;
  layer: Layer;
  displacement: number;
  quality: number;
  touches: number;
  status: ZoneStatus;
  mitigated_time: number | null;
  ended_time: number | null;
}

export interface PremiumDiscount {
  layer: Layer;
  high: number;
  high_time: number;
  low: number;
  low_time: number;
  equilibrium: number;
  equilibrium_upper: number;
  equilibrium_lower: number;
  position: number;
  zone: 'premium' | 'discount' | 'equilibrium' | 'above_range' | 'below_range';
}

export interface OteZone {
  direction: Direction3;
  layer: Layer;
  impulse_start: number;
  impulse_start_time: number;
  impulse_end: number;
  impulse_end_time: number;
  upper: number;
  lower: number;
  focus: number;
  active: boolean;
  price_in_zone: boolean;
}

export interface MtfFrame {
  timeframe: string;
  ready: boolean;
  candle_time: number | null;
  trend: Direction3 | null;
  structure: Direction3 | null;
  directional_regime: DirectionalRegime | null;
  volatility_regime: VolatilityRegime | null;
}

export interface MultiTimeframeContext {
  execution: MtfFrame;
  higher: MtfFrame[];
  directional_alignment: MtfAlignment;
  structure_alignment: MtfAlignment;
  volatility_aligned: boolean | null;
  regime_alignment: MtfAlignment;
}

export interface CandleFeatures {
  time: number;
  status: FeatureStatus;
  direction: 'up' | 'down' | 'flat';
  body_pct: number;
  upper_wick_pct: number;
  lower_wick_pct: number;
  range_atr: number | null;
  close_location: number;
  patterns: string[];
}

export interface DevelopingFeatures {
  swing_pivots: Pivot[];
  internal_pivots: Pivot[];
  swing_breaks: DevelopingBreak[];
  internal_breaks: DevelopingBreak[];
  sweeps: DevelopingSweep[];
  fair_value_gaps: FairValueGap[];
}

export interface AnalysisSnapshot {
  kind?: 'full' | 'live';
  symbol: string;
  timeframe: string;
  analysis_ready: boolean;
  reason: string | null;
  candle_time: number | null;
  forming_time: number | null;
  price: number | null;
  generated_at?: string;
  candles_analyzed?: number;
  trend?: {
    direction: Direction3;
    score: number;
    emas: {
      period: number;
      value: number;
      slope: number;
      normalized_slope: number | null;
      distance_atr: number | null;
    }[];
    stack: 'bullish' | 'bearish' | 'mixed';
    alignment_score: number;
    spread_atr: number | null;
    spread_change_atr: number | null;
    spread_state: 'expanding' | 'compressing' | 'flat';
    price_above_ema200: boolean | null;
  } | null;
  regime?: {
    primary: MarketRegime;
    directional: DirectionalRegime;
    volatility: VolatilityRegime;
    inputs: Record<string, number | string | null>;
  } | null;
  volatility?: {
    atr: number;
    atr_pct: number;
    atr_percentile: number | null;
    range_atr: number | null;
    realized_vol: number | null;
    regime: VolatilityRegime;
  } | null;
  momentum?: {
    rsi: number | null;
    rsi_slope: number | null;
    rsi_cross_50: 'up' | 'down' | null;
    rsi_overbought: boolean;
    rsi_oversold: boolean;
    roc: number | null;
    impulse_atr: number | null;
    acceleration: number | null;
    divergence: 'bullish' | 'bearish' | null;
  } | null;
  volume?: {
    volume: number;
    average: number | null;
    relative: number | null;
    zscore: number | null;
    percentile: number | null;
    spike: boolean;
    contraction: boolean;
  } | null;
  candle?: CandleFeatures | null;
  forming_candle?: CandleFeatures | null;
  swing_structure?: StructureState | null;
  internal_structure?: StructureState | null;
  liquidity?: LiquidityState | null;
  fair_value_gaps?: FairValueGap[];
  order_blocks?: OrderBlock[];
  premium_discount?: PremiumDiscount | null;
  ote?: OteZone | null;
  multi_timeframe?: MultiTimeframeContext | null;
  developing?: DevelopingFeatures | null;
  counts?: Record<string, number>;
  debug?: Record<string, unknown> | null;
}
