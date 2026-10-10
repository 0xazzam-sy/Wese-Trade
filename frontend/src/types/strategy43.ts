/**
 * Strategy 4.3 wire types (backend app.strategy43). `score` is «قوة الإشارة»: a weighted
 * evidence score out of 100 — never a probability of profit.
 */
export type Tier = 'A+' | 'A' | 'B' | 'C';

/** One open confirmed opportunity (scanner row / best opportunity of a symbol). */
export interface OpportunityDTO {
  id: string;
  symbol: string;
  timeframe: string;
  side: 'BUY' | 'SELL';
  tier: Tier;
  tier_ar: string;
  score: number;
  family: string;
  family_ar: string;
  state: string;
  state_ar: string;
  entry: number;
  stop: number;
  targets: [number, number, number];
  rr: [number, number, number];
  confirmed_time: number;
  valid_until: number;
  regime: string;
  regime_ar: string;
}

export interface OpportunitiesResponse {
  items: OpportunityDTO[];
  universe_size: number;
  markets_scanned: number;
  symbols_with_opportunity: number;
  last_scan_at: number | null;
  state: EngineState;
}

export type EngineState = 'running' | 'starting' | 'degraded' | 'stopped';

export interface SignalCounts {
  total: number;
  by_tier: Partial<Record<Tier, number>>;
}

export interface TelegramHealth {
  state: string;
  detail: string;
  bot_username: string | null;
  running: boolean;
  recipients: number;
  sent_24h: number;
  failed_24h: number;
  pending: number;
  last_sent_at: string | null;
  last_error: string;
  last_error_at: string | null;
  dropped: number;
}

/** «محرك الإشارات» production health. */
export interface EngineHealth {
  state: EngineState;
  state_ar: string;
  problems: string[];
  name: string;
  version: string;
  fingerprint: string;
  started_at: number | null;
  universe: string[];
  universe_size: number;
  streams: number;
  subscribed: number;
  markets_scanned: number;
  timeframes: string[];
  open_opportunities: number;
  open_by_tier: Record<Tier, number>;
  symbols_with_opportunity: number;
  market_status: string;
  evaluations: number;
  confirmed: number;
  last_candle_close: number | null;
  last_market_update: number | null;
  last_scan_at: number | null;
  last_signal_at: number | null;
  signals?: { today?: SignalCounts; '7d'?: SignalCounts; '30d'?: SignalCounts };
  execution?: { version: string; streams: number; confirmed: number; parent_source: string | null };
  telegram?: TelegramHealth | null;
  baseline_4_2?: {
    state: string;
    version: string;
    fingerprint: string;
    status: string | null;
  } | null;
}

/** Quality (not direction) styling of a tier badge. */
export const TIER_STYLE: Record<Tier, string> = {
  'A+': 'border-accent-strong/60 bg-accent/18 text-accent-strong',
  A: 'border-accent/45 bg-accent/10 text-accent',
  B: 'border-violet/40 bg-violet-soft text-violet',
  C: 'border-line-strong bg-sunken text-fg-muted',
};
