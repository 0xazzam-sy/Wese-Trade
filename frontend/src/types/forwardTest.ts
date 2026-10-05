/** Phase 4.2 forward-test wire types (backend app.forward_test). Paper results in R. */
export type ForwardStatus =
  'forward_testing' | 'paused' | 'stopped' | 'passed_forward_test' | 'failed_forward_test';

export interface ForwardStats {
  entered: number;
  wins: number;
  losses: number;
  ambiguous: number;
  win_rate: number | null;
  avg_r: number | null;
  median_r: number | null;
  expectancy: number | null;
  profit_factor: number | null;
  max_drawdown_r: number;
  total_r: number;
  gross_expectancy: number | null;
  gross_profit_factor: number | null;
  avg_hold_bars: number | null;
  avg_hold_hours: number | null;
}

export interface ForwardCounts {
  confirmed: number;
  active: number;
  closed_trades: number;
  wins: number;
  losses: number;
  ambiguous: number;
  expired_unfilled: number;
  invalidated: number;
  ended_by_run_stop: number;
}

export interface ForwardMetrics {
  counts: ForwardCounts;
  all: ForwardStats;
  recent: ForwardStats;
  by_timeframe: Record<string, ForwardStats>;
  by_symbol: Record<string, ForwardStats>;
  by_regime: Record<string, ForwardStats>;
  by_side: Record<string, ForwardStats>;
  by_score_bucket: Record<string, ForwardStats>;
  assessment: { verdict: string; reasons: string[] };
  elapsed_days: number;
  criteria: Record<string, number>;
}

export interface ForwardRun {
  id: number;
  strategy_version: string;
  fingerprint: string;
  research_version: string;
  started_at: string;
  stopped_at: string | null;
  status: ForwardStatus;
  status_ar: string;
  symbols: string[];
  timeframes: string[];
  cost_model: Record<string, number | string>;
  minimum_required_trades: number;
  minimum_days: number;
  notes: string;
  status_history: [string, string, string][];
  metrics: ForwardMetrics;
  config_matches_code: boolean;
  disclaimer_ar: string;
  health: ForwardHealth | null;
}

export interface ForwardHealth {
  state: 'running' | 'paused' | 'degraded' | 'stopped';
  problem: string | null;
  last_candle_close: number | null;
  last_evaluation_at: number | null;
  last_persist_ok_at: number | null;
  persist_errors: number;
  unavailable_symbols: string[];
  evaluations: number;
}

export interface ForwardStatusCard {
  name: string;
  version: string;
  fingerprint: string;
  disclaimer_ar: string;
  health: string;
  run: {
    id: number;
    status: ForwardStatus;
    status_ar: string;
    started_at: string;
    strategy_version: string;
    fingerprint: string;
  } | null;
  confirmed_signals?: number;
  closed_trades?: number;
  net_expectancy_r?: number | null;
  minimum_required_trades?: number;
}

export interface ForwardSignalRow {
  signal_id: string;
  strategy_version: string;
  symbol: string;
  timeframe: string;
  side: 'long' | 'short';
  score: number;
  regime: string | null;
  confirmed_at: string;
  entry: number;
  stop: number;
  tp1: number;
  tp2: number;
  tp3: number;
  state: string;
  net_r: number | null;
  gross_r: number | null;
}

export interface ForwardSignalFilters {
  symbol?: string;
  timeframe?: string;
  side?: string;
  state?: string;
}
