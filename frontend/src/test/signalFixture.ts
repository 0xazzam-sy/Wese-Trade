import type { SignalDTO, SignalEvaluationDTO, SignalView, TradePlanDTO } from '@/types/signal';

export const PLAN: TradePlanDTO = {
  entry_model: 'MARKET_ENTRY',
  entry_low: 100,
  entry_high: 100,
  preferred_entry: 100,
  stop: 98,
  invalidation: 98,
  stop_source: 'swing_low',
  risk: 2,
  risk_atr: 1,
  targets: [
    { price: 102, rr: 1, source: 'liquidity' },
    { price: 103.5, rr: 1.75, source: 'swing_high' },
    { price: 106, rr: 3, source: 'extension' },
  ],
  rr: [1, 1.75, 3],
};

export function evaluation(overrides: Partial<SignalEvaluationDTO> = {}): SignalEvaluationDTO {
  return {
    symbol: 'BTCUSDT',
    timeframe: '15m',
    candle_time: 1_700_000_000,
    developing: false,
    signal_class: 'NEUTRAL',
    side: null,
    score: 41,
    bull_score: 41,
    bear_score: 20,
    hypothesis: null,
    plan: null,
    neutral_reason: 'لا يوجد محفّز هيكلي على الشمعة الأخيرة',
    strategy_version: 'wese-trade-signal-4.0-test',
    ...overrides,
  };
}

export function signal(overrides: Partial<SignalDTO> = {}): SignalDTO {
  return {
    id: 'sig-1',
    symbol: 'BTCUSDT',
    timeframe: '15m',
    side: 'long',
    signal_class: 'BUY',
    family: 'TREND_CONTINUATION',
    score: 78.4,
    trigger_id: 'trg-1',
    trigger_time: 1_700_000_000,
    confirmed_time: 1_700_000_000,
    plan: PLAN,
    components: [{ name: 'htf', value: 0.8, weight: 20, points: 16 }],
    penalties: [],
    positive: ['الإطار الأعلى صاعد'],
    negative: ['الحجم أقل من المتوسط'],
    evidence: {},
    strategy_version: 'wese-trade-signal-4.0-test',
    regime: 'uptrend',
    state: 'active',
    state_time: 1_700_000_900,
    entered_time: 1_700_000_000,
    entry_price: 100,
    targets_hit: 0,
    exit_reason: null,
    closed_time: null,
    ambiguous: false,
    gross_r: null,
    net_r: null,
    history: [[1_700_000_000, 'confirmed']],
    ...overrides,
  };
}

export function view(overrides: Partial<SignalView> = {}): SignalView {
  return {
    symbol: 'BTCUSDT',
    timeframe: '15m',
    evaluation: null,
    developing: null,
    active: null,
    lastConfirmed: null,
    lastClosed: null,
    ...overrides,
  };
}
