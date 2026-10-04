/**
 * Wire types for the signal engine (backend app.signal_engine).
 * `score` is a 0-100 CONFLUENCE / setup-quality score. It is NOT a probability of profit
 * and must never be displayed as one. Signals are analytical; there is no trading API.
 */
export type SignalClass = 'STRONG_BUY' | 'BUY' | 'NEUTRAL' | 'SELL' | 'STRONG_SELL';
export type SignalSide = 'long' | 'short';
export type SetupFamily =
  'TREND_CONTINUATION' | 'PULLBACK_CONTINUATION' | 'BREAKOUT_CONTINUATION' | 'LIQUIDITY_REVERSAL';
export type SignalLifecycleState =
  | 'developing'
  | 'confirmed'
  | 'active'
  | 'tp1_hit'
  | 'tp2_hit'
  | 'tp3_hit'
  | 'stopped'
  | 'invalidated'
  | 'expired'
  | 'closed';

export interface TargetDTO {
  price: number;
  rr: number;
  source: string;
}

export interface TradePlanDTO {
  entry_model: 'MARKET_ENTRY' | 'ZONE_ENTRY';
  entry_low: number;
  entry_high: number;
  preferred_entry: number;
  stop: number;
  invalidation: number;
  stop_source: string;
  risk: number;
  risk_atr: number;
  targets: [TargetDTO, TargetDTO, TargetDTO];
  rr: [number, number, number];
}

export interface ComponentDTO {
  name: string;
  value: number;
  weight: number;
  points: number;
}

export interface PenaltyDTO {
  code: string;
  points: number;
  reason: string;
}

export interface HypothesisDTO {
  family: SetupFamily;
  side: SignalSide;
  trigger: { id: string; time: number; layer: string; type: string; direction: string };
  score: number;
  base_score: number;
  components: ComponentDTO[];
  penalties: PenaltyDTO[];
  positive: string[];
  negative: string[];
  regime: string | null;
}

export interface SignalEvaluationDTO {
  symbol: string;
  timeframe: string;
  candle_time: number | null;
  developing: boolean;
  signal_class: SignalClass;
  side: SignalSide | null;
  score: number;
  bull_score: number;
  bear_score: number;
  hypothesis: HypothesisDTO | null;
  plan: TradePlanDTO | null;
  neutral_reason: string | null;
  strategy_version: string;
}

export interface SignalDTO {
  id: string;
  symbol: string;
  timeframe: string;
  side: SignalSide;
  signal_class: SignalClass;
  family: SetupFamily;
  score: number;
  trigger_id: string;
  trigger_time: number;
  confirmed_time: number;
  plan: TradePlanDTO;
  components: ComponentDTO[];
  penalties: PenaltyDTO[];
  positive: string[];
  negative: string[];
  evidence: Record<string, unknown>;
  strategy_version: string;
  regime: string | null;
  state: SignalLifecycleState;
  state_time: number;
  entered_time: number | null;
  entry_price: number | null;
  targets_hit: number;
  exit_reason: string | null;
  closed_time: number | null;
  ambiguous: boolean;
  gross_r: number | null;
  net_r: number | null;
  history: [number, string][];
}

/** Per-stream signal view: what the panel and chart overlays display. */
export interface SignalView {
  symbol: string;
  timeframe: string;
  evaluation: SignalEvaluationDTO | null; // last closed-candle evaluation
  developing: SignalEvaluationDTO | null; // forming candle (never a trade)
  active: SignalDTO | null; // open confirmed signal
  lastConfirmed: SignalDTO | null;
  lastClosed: SignalDTO | null;
}
