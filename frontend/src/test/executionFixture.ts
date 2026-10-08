import type {
  ExecutionDecision,
  ExecutionParent,
  ExecutionPlan,
  ExecutionSignal,
  ExecutionState,
} from '@/types/execution';

/** Execution-layer payloads shaped exactly like the backend `execution.update`. */
export const PARENT: ExecutionParent = {
  signal_id: 'ETHUSDT-15m-1789718400-long',
  strategy: 'Wese Trade Forward 4.2',
  strategy_version: 'wese-trade-forward-4.2-a03e20f1d4',
  fingerprint: '4.2-a03e20f',
  symbol: 'ETHUSDT',
  timeframe: '15m',
  side: 1,
  family: 'TREND_CONTINUATION',
  score: 81.2,
  state: 'confirmed',
  confirmed_time: 1_789_718_400,
  entry_low: 2480.0,
  entry_high: 2490.0,
  entry: 2485.14,
  stop: 2467.73,
  invalidation: 2467.73,
  targets: [2508.38, 2518.31, 2558.56],
};

export const EXEC_PLAN: ExecutionPlan = {
  side: 1,
  entry: 2483.9,
  parent_entry: 2485.14,
  stop: 2467.73,
  parent_stop: 2467.73,
  stop_source: 'parent',
  targets: [2508.38, 2518.31, 2558.56],
  target_sources: ['parent_tp1', 'parent_tp2', 'parent_tp3'],
  rr: [1.51, 2.13, 4.62],
};

export function execSignal(o: Partial<ExecutionSignal> = {}): ExecutionSignal {
  return {
    id: 'x-ETHUSDT-5m-1789718400-long-1789719000',
    symbol: 'ETHUSDT',
    timeframe: '5m',
    side: 1,
    score: 81,
    confirmed_time: 1_789_719_000,
    candle_time: 1_789_718_700,
    valid_until: 1_789_719_300,
    plan: EXEC_PLAN,
    parent: PARENT,
    reasons: ['اتجاه 15m صاعد (Strategy 4.2)', 'السعر أعاد اختبار دعم قوي وارتد منه'],
    trigger: 'bos',
    state: 'ready',
    state_ar: 'جاهز للدخول',
    state_time: 1_789_719_000,
    entered_time: null,
    targets_hit: 0,
    closed_time: null,
    execution_version: 'wese-trade-execution-1.1',
    history: [[1_789_719_000, 'ready']],
    ...o,
  };
}

export function execState(
  decision: ExecutionDecision,
  o: Partial<ExecutionState> = {},
  timeframe = '5m',
): ExecutionState {
  const parent = decision === 'NO_SETUP' ? null : PARENT;
  const signal = decision === 'BUY' ? execSignal({ timeframe }) : null;
  const headline: Record<ExecutionDecision, string> = {
    BUY: 'تم تأكيد توقيت الدخول للصفقة الصاعدة.',
    SELL: 'تم تأكيد توقيت الدخول للصفقة الهابطة.',
    WAIT: 'الصفقة صاعدة لكن توقيت الدخول غير مناسب بعد.',
    ENTRY_MISSED: 'فاتت منطقة الدخول — لا تلاحق السعر.',
    NO_SETUP: 'لا توجد فرصة تداول مؤكدة حالياً.',
  };
  return {
    symbol: 'ETHUSDT',
    timeframe,
    execution_version: 'wese-trade-execution-1.1',
    evaluation: {
      candle_time: 1_789_718_700,
      decision,
      decision_ar: decision,
      score: decision === 'NO_SETUP' ? 0 : decision === 'BUY' ? 81 : 52,
      score_band: decision === 'NO_SETUP' ? null : decision === 'BUY' ? 'strong' : 'weak',
      side: parent ? 1 : 0,
      headline: headline[decision],
      reasons: parent
        ? [
            'اتجاه 15m صاعد (Strategy 4.2)',
            'EMA20 فوق EMA50 والسعر أعلاها',
            'تم تأكيد BOS داخلي صاعد',
          ]
        : [],
      cautions: decision === 'WAIT' ? ['لا توجد شمعة تأكيد على هذا الفريم بعد'] : [],
      components: {},
      parent,
      plan: parent ? EXEC_PLAN : null,
      trigger: decision === 'BUY' ? 'bos' : null,
      micro: { status: 'ok', spread_bp: 0.4, spread_normal_bp: 0.4, book_imbalance: 0.2,
               flow_imbalance: 0.1, book_age_s: 0.3, trade_age_s: 1.2, reasons: [] }, // prettier-ignore
    },
    signal,
    markers: signal ? [{ id: signal.id, time: signal.candle_time, side: 1, state: 'ready' }] : [],
    overlay: {
      ema: { '20': 2484.1, '50': 2480.3, '200': 2470.2 },
      levels: [
        { price: 2481.0, strength: 8.4, grade: 'strong', kind: 'support' },
        { price: 2512.5, strength: 4.1, grade: 'medium', kind: 'resistance' },
      ],
    },
    micro: null,
    ...o,
  };
}
