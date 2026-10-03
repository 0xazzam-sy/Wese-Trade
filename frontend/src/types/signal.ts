/** Mirrors backend `app.signal_engine.contracts`. Nothing in the UI generates signals. */
export type SignalLabel = 'STRONG_BUY' | 'BUY' | 'NEUTRAL' | 'SELL' | 'STRONG_SELL';

export type SignalState = 'developing' | 'confirmed' | 'invalidated' | 'closed';

export interface TradePlanDTO {
  entry: string;
  stop_loss: string;
  take_profits: [string, string, string];
  risk_reward: string;
}

export interface SignalDTO {
  symbol: string;
  timeframe: string;
  label: SignalLabel;
  state: SignalState;
  /** Strategy confluence score 0-100. NOT a probability of winning. */
  confidence: number;
  plan: TradePlanDTO | null;
  generated_at: string;
  candle_open_time: string;
  strategy_version: string;
}
