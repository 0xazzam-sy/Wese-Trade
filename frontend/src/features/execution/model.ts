import type { OverlayLine } from '@/features/analysis/overlays/overlayModel';
import { PLAN_LABELS } from '@/features/analysis/overlays/overlayModel';
import { MARKER_TEXT, type MarkerSpec } from '@/features/signals/chart/chartSignals';
import type { OverlayToggles } from '@/stores/overlayStore';
import type {
  ExecutionDecision,
  ExecutionLifecycle,
  ExecutionPlan,
  ExecutionState,
  ScoreBand,
} from '@/types/execution';

/**
 * Execution timing (1m / 5m / 10m). Pure helpers: every value comes from the backend
 * execution layer; nothing here decides a trade.
 */
export const EXECUTION_TIMEFRAMES: readonly string[] = ['1m', '5m', '10m'];

export function isExecutionTimeframe(timeframe: string): boolean {
  return EXECUTION_TIMEFRAMES.includes(timeframe);
}

export const EXECUTION_AR = {
  decisionTitle: 'قرار Wese Trade',
  direction: 'الاتجاه',
  timing: 'توقيت الدخول',
  score: 'قوة توقيت الدخول',
  scoreHint:
    'قوة توقيت الدخول من 100: مدى ملاءمة ظروف الفريم الحالي للدخول في الصفقة الأساسية — ليست احتمال ربح.',
  parent: 'الفرصة الأساسية',
  reasons: 'سبب القرار',
  cautions: 'ما ينقص للدخول',
  plan: 'خطة الصفقة',
  noSetup: 'لا توجد فرصة تداول مؤكدة حالياً.',
  waiting: 'بانتظار التحليل…',
  risk: 'التداول ينطوي على مخاطر — القرار والتنفيذ مسؤولية المستخدم. لا توجد نتائج مضمونة.',
  roleTitle: {
    '1m': 'توقيت دقيق للدخول',
    '5m': 'تأكيد التنفيذ',
    '10m': 'ربط الإطار الأعلى بالتنفيذ',
  } as Record<string, string>,
} as const;

export const DECISION_TEXT: Record<ExecutionDecision, string> = {
  BUY: 'BUY — شراء',
  SELL: 'SELL — بيع',
  WAIT: 'WAIT — انتظر',
  ENTRY_MISSED: 'ENTRY MISSED — فاتت منطقة الدخول',
  NO_SETUP: 'لا توجد فرصة حالية',
};

export const DECISION_STYLE: Record<ExecutionDecision, string> = {
  BUY: 'bg-bull/15 text-bull border-bull/50',
  SELL: 'bg-bear/15 text-bear border-bear/50',
  WAIT: 'bg-warning/10 text-warning border-warning/40',
  ENTRY_MISSED: 'bg-sig-neutral/10 text-fg-muted border-line-strong',
  NO_SETUP: 'bg-sig-neutral/10 text-fg border-line',
};

export const TIMING_TEXT: Record<ExecutionDecision, string> = {
  BUY: 'مؤكد',
  SELL: 'مؤكد',
  WAIT: 'غير مناسب بعد',
  ENTRY_MISSED: 'فات',
  NO_SETUP: '—',
};

export const BAND_AR: Record<ScoreBand, string> = {
  poor: 'ضعيف جداً — انتظر',
  weak: 'ضعيف',
  acceptable: 'مقبول',
  strong: 'قوي',
  very_strong: 'قوي جداً',
};

export const LIFECYCLE_AR: Record<ExecutionLifecycle | 'waiting', string> = {
  waiting: 'بانتظار التوقيت',
  ready: 'جاهز للدخول',
  active: 'صفقة نشطة',
  tp1_hit: 'تحقق الهدف 1',
  tp2_hit: 'تحقق الهدف 2',
  tp3_hit: 'تحقق الهدف 3',
  stopped: 'ضُرب وقف الخسارة',
  expired: 'انتهت الصلاحية',
  entry_missed: 'فاتت منطقة الدخول',
};

export const FAMILY_AR: Record<string, string> = {
  TREND_CONTINUATION: 'Trend Continuation',
  PULLBACK_CONTINUATION: 'Pullback Continuation',
  BREAKOUT_CONTINUATION: 'Breakout Continuation',
  LIQUIDITY_REVERSAL: 'Liquidity Reversal',
};

export const MICRO_AR: Record<string, string> = {
  ok: 'بيانات السوق اللحظية سليمة',
  degraded: 'بيانات السوق اللحظية متذبذبة',
  stale: 'بيانات السوق اللحظية متأخرة',
  unavailable: 'بيانات السوق اللحظية غير متاحة — تحليل الشموع والهيكل فقط',
};

export const REGIME_AR: Record<string, string> = {
  strong_uptrend: 'اتجاه صاعد قوي',
  uptrend: 'اتجاه صاعد',
  ranging: 'نطاق عرضي',
  downtrend: 'اتجاه هابط',
  strong_downtrend: 'اتجاه هابط قوي',
  high_volatility: 'تذبذب مرتفع',
  low_volatility: 'تذبذب منخفض',
  transitional: 'مرحلة انتقالية',
};

/** Direction of the active trade context (from the parent setup), not of one candle. */
export function directionText(state: ExecutionState | null): {
  label: string;
  tone: 'bullish' | 'bearish' | 'neutral';
} {
  const side = state?.evaluation?.side ?? 0;
  if (side === 1) return { label: 'صاعد', tone: 'bullish' };
  if (side === -1) return { label: 'هابط', tone: 'bearish' };
  return { label: 'لا يوجد اتجاه صفقة', tone: 'neutral' };
}

/** The plan to show: the confirmed signal's (frozen) plan, else the parent-context preview. */
export function displayPlan(state: ExecutionState | null): ExecutionPlan | null {
  if (!state) return null;
  const decision = state.evaluation?.decision;
  if (state.signal && (decision === 'BUY' || decision === 'SELL')) return state.signal.plan;
  return state.evaluation?.plan ?? null;
}

const FINAL = new Set<ExecutionLifecycle>(['tp3_hit', 'stopped', 'expired', 'entry_missed']);

/** BUY / SELL markers on the exact confirmation candles (backend-persisted ids). */
export function executionMarkers(
  state: ExecutionState | null,
  enabled: boolean,
  hasCandle: (time: number) => boolean = () => true,
): MarkerSpec[] {
  if (!enabled || !state) return [];
  return state.markers
    .filter((m) => hasCandle(m.time))
    .map((m) => {
      const side = m.side === 1 ? 'long' : 'short';
      return {
        id: m.id,
        time: m.time,
        side,
        position: side === 'long' ? 'belowBar' : 'aboveBar',
        shape: side === 'long' ? 'arrowUp' : 'arrowDown',
        text: MARKER_TEXT[side],
        active: !FINAL.has(m.state),
      };
    });
}

/**
 * Entry / SL / TP1-3 lines. With a confirmed open execution signal: its frozen plan from the
 * confirmation candle. With only a parent context (WAIT): the parent zone plan, dashed.
 */
export function executionPlanLines(
  state: ExecutionState | null,
  toggles: OverlayToggles,
): OverlayLine[] {
  const ev = state?.evaluation;
  if (!toggles.tradePlan || !state || !ev?.parent) return [];
  const open = state.signal && !FINAL.has(state.signal.state) ? state.signal : null;
  if (!open && ev.decision !== 'WAIT') return [];
  const plan = open ? open.plan : ev.plan;
  if (!plan) return [];
  const from = open ? open.candle_time : ev.parent.confirmed_time;
  const preview = !open;
  const id = open ? open.id : `ctx:${ev.parent.signal_id}`;
  const hit = open?.targets_hit ?? 0;
  return [
    {
      id: `xplan:${id}:entry`,
      from,
      to: null,
      price: plan.entry,
      kind: 'plan-entry',
      dashed: preview,
      faded: false,
      label: PLAN_LABELS.entry,
    },
    {
      id: `xplan:${id}:sl`,
      from,
      to: null,
      price: plan.stop,
      kind: 'plan-stop',
      dashed: preview,
      faded: false,
      label: PLAN_LABELS.stop,
    },
    ...plan.targets.map((price, i) => ({
      id: `xplan:${id}:tp${String(i + 1)}`,
      from,
      to: null,
      price,
      kind: 'plan-target' as const,
      dashed: preview || i < hit,
      faded: i < hit,
      label: PLAN_LABELS.target(i + 1),
    })),
  ];
}

const GRADE_AR = { strong: 'قوي', medium: 'متوسط', weak: 'ضعيف' } as const;

/** Support / resistance levels with strength (scalp-6 level book), nearest first. */
export function levelLines(
  state: ExecutionState | null,
  toggles: OverlayToggles,
  from: number,
): OverlayLine[] {
  if (!toggles.levels || !state?.overlay) return [];
  return state.overlay.levels
    .filter((lv) => lv.grade !== 'weak')
    .map((lv, i) => ({
      id: `sr:${lv.kind}:${String(i)}:${lv.price.toFixed(8)}`,
      from,
      to: null,
      price: lv.price,
      kind: lv.kind === 'support' ? ('sr-support' as const) : ('sr-resistance' as const),
      dashed: lv.grade === 'medium',
      faded: lv.grade === 'medium',
      label: `${lv.kind === 'support' ? 'دعم' : 'مقاومة'} ${GRADE_AR[lv.grade]} · ${lv.strength.toFixed(1)}`,
    }));
}
