import type { OpportunityDTO } from './strategy43';

/**
 * Wire types of the execution layer (backend app.execution, `execution.update`).
 *
 * 1m / 5m / 10m never create an independent trade thesis: a BUY / SELL here is an
 * entry-timing confirmation for an open Strategy 4.2 signal (15m / 30m / 1h, the "parent").
 * `score` («قوة توقيت الدخول») describes execution conditions — it is NOT a win probability.
 */
export type ExecutionDecision = 'BUY' | 'SELL' | 'WAIT' | 'ENTRY_MISSED' | 'NO_SETUP';
export type ExecutionLifecycle =
  'ready' | 'active' | 'tp1_hit' | 'tp2_hit' | 'tp3_hit' | 'stopped' | 'expired' | 'entry_missed';
export type ScoreBand = 'poor' | 'weak' | 'acceptable' | 'strong' | 'very_strong';

export interface ExecutionParent {
  signal_id: string;
  strategy: string;
  strategy_version: string;
  fingerprint: string;
  symbol: string;
  timeframe: string;
  side: 1 | -1;
  family: string;
  score: number;
  state: string;
  confirmed_time: number;
  entry_low: number;
  entry_high: number;
  entry: number;
  stop: number;
  invalidation: number;
  targets: [number, number, number];
}

export interface ExecutionPlan {
  side: 1 | -1;
  entry: number;
  parent_entry: number;
  stop: number;
  parent_stop: number;
  stop_source: string;
  targets: [number, number, number];
  target_sources: string[];
  rr: [number, number, number];
}

export interface ExecutionMicro {
  status: 'ok' | 'degraded' | 'stale' | 'unavailable';
  spread_bp: number | null;
  spread_normal_bp: number | null;
  book_imbalance: number | null;
  flow_imbalance: number | null;
  book_age_s: number | null;
  trade_age_s: number | null;
  reasons: string[];
}

export interface ExecutionEvaluation {
  candle_time: number | null;
  decision: ExecutionDecision;
  decision_ar: string;
  score: number;
  score_band: ScoreBand | null;
  side: -1 | 0 | 1;
  headline: string;
  reasons: string[];
  cautions: string[];
  components: Record<string, number>;
  parent: ExecutionParent | null;
  plan: ExecutionPlan | null;
  trigger: string | null;
  micro: ExecutionMicro | null;
}

export interface ExecutionSignal {
  id: string;
  symbol: string;
  timeframe: string;
  side: 1 | -1;
  score: number;
  confirmed_time: number;
  /** Open time of the confirmation candle: the BUY / SELL marker sits on it. */
  candle_time: number;
  valid_until: number;
  plan: ExecutionPlan;
  parent: ExecutionParent;
  reasons: string[];
  trigger: string;
  state: ExecutionLifecycle;
  state_ar: string;
  state_time: number;
  entered_time: number | null;
  targets_hit: number;
  closed_time: number | null;
  execution_version: string;
  history: [number, string][];
}

export interface ExecutionMarker {
  id: string;
  time: number;
  side: 1 | -1;
  state: ExecutionLifecycle;
}

export interface ExecutionLevel {
  price: number;
  strength: number;
  grade: 'strong' | 'medium' | 'weak';
  kind: 'support' | 'resistance';
}

export interface ExecutionState {
  symbol: string;
  timeframe: string;
  execution_version: string;
  evaluation: ExecutionEvaluation | null;
  signal: ExecutionSignal | null;
  markers: ExecutionMarker[];
  overlay: {
    ema: Record<'20' | '50' | '200', number | null>;
    levels: ExecutionLevel[];
  } | null;
  micro: ExecutionMicro | null;
  /** v1.2.1: best open Strategy 4.3 opportunity of this symbol (15m / 30m / 1h). */
  best?: OpportunityDTO | null;
}
