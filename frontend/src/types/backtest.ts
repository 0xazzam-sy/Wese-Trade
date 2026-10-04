/** Backtest report wire types (backend app.backtesting.report). All results in R multiples. */
export interface BacktestStats {
  signals: number;
  entered: number;
  wins: number;
  losses: number;
  ambiguous: number;
  expired: number;
  win_rate: number | null;
  expectancy: number | null;
  median_r: number | null;
  profit_factor: number | null;
  max_drawdown_r: number;
  total_r: number;
  gross_expectancy: number | null;
  gross_profit_factor: number | null;
  avg_hold_bars: number | null;
  tp1_rate: number | null;
  tp2_rate: number | null;
  tp3_rate: number | null;
  max_consecutive_losses: number;
}

export interface CalibrationRow {
  bucket: string;
  signals: number;
  entered: number;
  win_rate: number | null;
  expectancy: number | null;
  profit_factor: number | null;
}

export interface BacktestSplit {
  overall: BacktestStats;
  by_symbol: Record<string, BacktestStats>;
  by_timeframe: Record<string, BacktestStats>;
  by_setup: Record<string, BacktestStats>;
  by_regime: Record<string, BacktestStats>;
  calibration: CalibrationRow[];
  score_monotonic: boolean;
}

export interface BacktestRunSummary {
  id: number;
  name: string;
  strategy_version: string;
  created_at: string;
  overall: BacktestStats | null;
  holdout: BacktestStats | null;
}

export interface BacktestRun {
  id: number;
  name: string;
  strategy_version: string;
  created_at: string;
  config: Record<string, unknown>;
  data: unknown[];
  summary: { all: BacktestSplit; dev: BacktestSplit; holdout: BacktestSplit };
}
