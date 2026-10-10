import { ALIGNMENT_AR, DIRECTION_AR, VOLATILITY_AR, ZONE_AR } from '@/features/analysis/lib/labels';
import type { AnalysisSnapshot, Direction3, StructureState } from '@/types/analysis';
import type { Tier } from '@/types/strategy43';
import type {
  ComponentDTO,
  PenaltyDTO,
  SignalSide,
  SignalView,
  StrategyInfo,
} from '@/types/signal';

import { signalDisplay, type SignalDisplay } from './display';
import { FAMILY_AR } from './labels';

/**
 * Turns the REAL engine output (analysis snapshot + signal evaluation/signal) into the
 * Arabic explanation shown in the analysis panel. Pure and side-effect free: nothing here
 * computes a signal, changes a threshold or invents a number — it only describes values
 * the backend already produced.
 */

export type ExplainTone = 'positive' | 'negative' | 'neutral';

export type CategoryKey =
  | 'trend'
  | 'swing'
  | 'internal'
  | 'mtf'
  | 'liquidity'
  | 'location'
  | 'momentum'
  | 'volume'
  | 'volatility'
  | 'displacement'
  | 'candle'
  | 'opposing'
  | 'penalties';

export interface CategoryRow {
  key: CategoryKey;
  label: string;
  /** Short state, e.g. «صاعد · BOS». */
  state: string;
  /** Engine contribution of this category (points) and its maximum (weight). */
  points: number | null;
  max: number | null;
  explanation: string;
  tone: ExplainTone;
}

export type Decision = 'BUY' | 'SELL' | 'NEUTRAL';

export interface Explanation {
  decision: Decision;
  decisionLabel: string;
  /** Answer to «هل في صفقة؟». */
  tradeLine: string;
  /** Sentence under the decision badge. */
  headline: string;
  /** Answer to «ليش؟». */
  reason: string;
  direction: { label: string; detail: string; tone: Direction3 | null };
  /** Analytical bias (research timeframes and neutral states). Never a trade. */
  bias: Direction3 | null;
  biasLabel: string | null;
  /** Strategy-conditions strength, 0-100. NOT a probability. */
  score: number | null;
  /** «جودة الفرصة» of a confirmed Strategy 4.3 signal, e.g. «B — جيدة». */
  tierLabel: string | null;
  tier: Tier | null;
  /** Score belongs to a candidate that did NOT become a signal. */
  candidateScore: boolean;
  blockers: string[];
  positives: string[];
  categories: CategoryRow[];
  display: SignalDisplay;
}

export const NO_ENTRY_TEXT = 'لا توجد فرصة مناسبة على هذا الفريم حالياً';
export const OUT_OF_SCOPE_TEXT = 'الفرص الأساسية تصدر على 15m و30m و1h — هذا الفريم لتوقيت الدخول.';
export const SCORE_LABEL = 'قوة الإشارة';
export const SCORE_TOOLTIP = 'قوة الإشارة تقيس توافق أدلة السوق من 100 وليست احتمال نجاح الصفقة.';

const BIAS_AR: Record<Direction3, string> = {
  bullish: 'ميل صاعد',
  bearish: 'ميل هابط',
  neutral: 'ميل محايد',
};

export const CATEGORY_LABELS: { key: CategoryKey; label: string; component?: string }[] = [
  { key: 'trend', label: 'الاتجاه', component: 'trend' },
  { key: 'swing', label: 'الهيكل الرئيسي', component: 'structure' },
  { key: 'internal', label: 'الهيكل الداخلي' },
  { key: 'mtf', label: 'توافق الفريمات', component: 'htf' },
  { key: 'liquidity', label: 'السيولة', component: 'liquidity' },
  { key: 'location', label: 'موقع السعر', component: 'location' },
  { key: 'momentum', label: 'الزخم', component: 'momentum' },
  { key: 'volume', label: 'الحجم', component: 'volume' },
  { key: 'volatility', label: 'التذبذب' },
  { key: 'displacement', label: 'الإزاحة', component: 'displacement' },
  { key: 'candle', label: 'تأكيد الشموع', component: 'candle' },
  { key: 'opposing', label: 'مناطق معاكسة' },
  { key: 'penalties', label: 'العقوبات والموانع' },
];

/** Engine penalty code → the category it weakens. */
const PENALTY_CATEGORY: Record<string, CategoryKey> = {
  htf_strong_opposition: 'mtf',
  htf_first_opposed: 'mtf',
  extreme_location: 'location',
  overextended: 'location',
  extreme_volatility: 'volatility',
  volume_contradiction: 'volume',
  momentum_opposed: 'momentum',
  opposite_divergence: 'momentum',
  adverse_sweep: 'liquidity',
  opposing_zone_ahead: 'opposing',
  transitional_regime: 'trend',
};

const sign = (d: Direction3 | null | undefined, side: SignalSide | null): ExplainTone => {
  if (!d || d === 'neutral' || !side) return 'neutral';
  return (d === 'bullish') === (side === 'long') ? 'positive' : 'negative';
};

function ratioTone(points: number | null, max: number | null): ExplainTone | null {
  if (points === null || max === null || max <= 0) return null;
  const r = points / max;
  if (r >= 0.6) return 'positive';
  if (r <= 0.2) return 'negative';
  return 'neutral';
}

function structureState(s: StructureState | null | undefined): string {
  if (!s) return 'غير متاح';
  const e = s.last_event;
  const tag = e ? ` · ${e.type === 'CHOCH' ? 'CHoCH' : 'BOS'}` : '';
  return `${DIRECTION_AR[s.direction]}${tag}`;
}

function structureText(s: StructureState | null | undefined, layer: string): string {
  if (!s) return `لا تتوفر بيانات ${layer} بعد.`;
  const e = s.last_event;
  if (!e) return `${layer} ${DIRECTION_AR[s.direction]} دون كسر هيكلي حديث.`;
  const kind = e.type === 'CHOCH' ? 'تغيّر في الطابع (CHoCH)' : 'كسر هيكل (BOS)';
  return `${layer} ${DIRECTION_AR[s.direction]}؛ آخر حدث ${kind} ${DIRECTION_AR[e.direction]}.`;
}

/** Analytical bias from the snapshot: EMA trend and main structure must agree. */
export function analyticalBias(snapshot: AnalysisSnapshot | null): Direction3 | null {
  if (!snapshot?.analysis_ready) return null;
  const trend = snapshot.trend?.direction;
  const swing = snapshot.swing_structure?.direction;
  if (!trend || !swing) return 'neutral';
  return trend === swing ? trend : 'neutral';
}

function componentMap(components: ComponentDTO[] | undefined): Map<string, ComponentDTO> {
  return new Map((components ?? []).map((c) => [c.name, c]));
}

function snapshotRow(
  key: CategoryKey,
  s: AnalysisSnapshot,
  side: SignalSide | null,
): Pick<CategoryRow, 'state' | 'explanation' | 'tone'> {
  switch (key) {
    case 'trend': {
      const t = s.trend;
      if (!t)
        return { state: 'غير متاح', explanation: 'المتوسطات غير متاحة بعد.', tone: 'neutral' };
      const stack = t.stack === 'mixed' ? 'متداخلة' : DIRECTION_AR[t.stack];
      const ema200 =
        t.price_above_ema200 === null
          ? ''
          : t.price_above_ema200
            ? '، والسعر فوق EMA 200'
            : '، والسعر تحت EMA 200';
      return {
        state: DIRECTION_AR[t.direction],
        explanation: `الاتجاه ${DIRECTION_AR[t.direction]} والمتوسطات ${stack}${ema200}.`,
        tone: sign(t.direction, side),
      };
    }
    case 'swing':
      return {
        state: structureState(s.swing_structure),
        explanation: structureText(s.swing_structure, 'الهيكل الرئيسي'),
        tone: sign(s.swing_structure?.direction, side),
      };
    case 'internal':
      return {
        state: structureState(s.internal_structure),
        explanation: structureText(s.internal_structure, 'الهيكل الداخلي'),
        tone: sign(s.internal_structure?.direction, side),
      };
    case 'mtf': {
      const m = s.multi_timeframe;
      if (!m)
        return {
          state: 'غير متاح',
          explanation: 'سياق الفريمات الأعلى غير متاح.',
          tone: 'neutral',
        };
      const frames = m.higher
        .filter((f) => f.ready && f.trend)
        .map((f) => `${f.timeframe} ${DIRECTION_AR[f.trend ?? 'neutral']}`)
        .join('، ');
      const al = m.directional_alignment;
      const dir: Direction3 = al.includes('bull')
        ? 'bullish'
        : al.includes('bear')
          ? 'bearish'
          : 'neutral';
      return {
        state: ALIGNMENT_AR[al],
        explanation: frames ? `الفريمات الأعلى: ${frames}.` : 'الفريمات الأعلى غير جاهزة بعد.',
        tone: al === 'countertrend' || al === 'mixed' ? 'negative' : sign(dir, side),
      };
    }
    case 'liquidity': {
      const l = s.liquidity;
      if (!l)
        return { state: 'غير متاح', explanation: 'بيانات السيولة غير متاحة.', tone: 'neutral' };
      const sweep = l.sweeps.at(-1);
      const sweepText = sweep
        ? ` آخر سحب: ${sweep.side === 'buy_side' ? 'سيولة علوية' : 'سيولة سفلية'}.`
        : '';
      return {
        state: `علوية ${String(l.active_buy_side)} · سفلية ${String(l.active_sell_side)}`,
        explanation: `مستويات سيولة نشطة: ${String(l.active_buy_side)} فوق السعر و${String(l.active_sell_side)} تحته.${sweepText}`,
        tone: 'neutral',
      };
    }
    case 'location': {
      const pd = s.premium_discount;
      if (!pd)
        return {
          state: 'غير متاح',
          explanation: 'نطاق Premium/Discount غير متاح.',
          tone: 'neutral',
        };
      const ote = s.ote?.price_in_zone ? ' السعر داخل منطقة OTE.' : '';
      const good =
        side === 'long' ? pd.zone === 'discount' : side === 'short' ? pd.zone === 'premium' : null;
      return {
        state: `${ZONE_AR[pd.zone]}${s.ote?.price_in_zone ? ' · OTE' : ''}`,
        explanation: `السعر عند ${pd.position.toFixed(0)}% من النطاق (${ZONE_AR[pd.zone]}).${ote}`,
        tone: good === null ? 'neutral' : good ? 'positive' : 'neutral',
      };
    }
    case 'momentum': {
      const m = s.momentum;
      if (m?.rsi == null)
        return { state: 'غير متاح', explanation: 'مؤشر RSI غير متاح.', tone: 'neutral' };
      const slope = (m.rsi_slope ?? 0) > 0 ? 'متصاعد' : (m.rsi_slope ?? 0) < 0 ? 'متراجع' : 'مستقر';
      const div = m.divergence ? `، مع انحراف ${DIRECTION_AR[m.divergence]}` : '';
      return {
        state: `RSI ${m.rsi.toFixed(0)}`,
        explanation: `RSI عند ${m.rsi.toFixed(0)} وزخمه ${slope}${div}.`,
        tone: sign(m.rsi >= 50 ? 'bullish' : 'bearish', side),
      };
    }
    case 'volume': {
      const v = s.volume;
      if (v?.relative == null)
        return { state: 'غير متاح', explanation: 'الحجم النسبي غير متاح.', tone: 'neutral' };
      const word = v.spike ? 'ارتفاع حاد' : v.contraction ? 'انكماش' : 'ضمن المعدل';
      return {
        state: `×${v.relative.toFixed(2)}`,
        explanation: `الحجم ×${v.relative.toFixed(2)} من المتوسط (${word}).`,
        tone: v.contraction ? 'negative' : v.relative >= 1 ? 'positive' : 'neutral',
      };
    }
    case 'volatility': {
      const v = s.volatility;
      if (!v) return { state: 'غير متاح', explanation: 'التذبذب غير متاح.', tone: 'neutral' };
      const hot = v.regime === 'high' || v.regime === 'extreme';
      return {
        state: VOLATILITY_AR[v.regime],
        explanation: `ATR = ${v.atr_pct.toFixed(2)}% من السعر؛ التذبذب ${VOLATILITY_AR[v.regime]}.`,
        tone: v.regime === 'extreme' ? 'negative' : hot ? 'neutral' : 'positive',
      };
    }
    case 'displacement': {
      const e = s.internal_structure?.last_event ?? s.swing_structure?.last_event;
      if (!e)
        return {
          state: 'لا يوجد',
          explanation: 'لا يوجد كسر هيكلي حديث لقياس الإزاحة.',
          tone: 'neutral',
        };
      const strong = e.displacement >= 60;
      return {
        state: `${e.displacement.toFixed(0)}/100`,
        explanation: `قوة اندفاع آخر كسر (${e.type === 'CHOCH' ? 'CHoCH' : 'BOS'} ${DIRECTION_AR[e.direction]}): ${e.displacement.toFixed(0)}/100${strong ? ' — اندفاع قوي' : ''}.`,
        tone: strong ? sign(e.direction, side) : 'neutral',
      };
    }
    case 'candle': {
      const c = s.candle;
      if (!c) return { state: 'غير متاح', explanation: 'لا تتوفر شمعة مغلقة.', tone: 'neutral' };
      const dir: Direction3 =
        c.direction === 'up' ? 'bullish' : c.direction === 'down' ? 'bearish' : 'neutral';
      const word = c.direction === 'up' ? 'صاعدة' : c.direction === 'down' ? 'هابطة' : 'محايدة';
      return {
        state: `${word} · جسم ${(c.body_pct * 100).toFixed(0)}%`,
        explanation: `آخر شمعة مغلقة ${word}، جسمها ${(c.body_pct * 100).toFixed(0)}% من مداها.`,
        tone: c.body_pct >= 0.5 ? sign(dir, side) : 'neutral',
      };
    }
    case 'opposing':
      return opposingZones(s, side);
    case 'penalties':
      return { state: 'لا يوجد', explanation: 'لا توجد عقوبات مطبّقة.', tone: 'neutral' };
  }
}

/** Active opposite OB/FVG within 1 ATR in the trade (or bias) direction. */
function opposingZones(
  s: AnalysisSnapshot,
  side: SignalSide | null,
): Pick<CategoryRow, 'state' | 'explanation' | 'tone'> {
  const atr = s.volatility?.atr;
  if (!side || s.price === null || !atr) {
    return {
      state: '--',
      explanation: 'لا يوجد اتجاه مرجّح لتقييم المناطق المعاكسة.',
      tone: 'neutral',
    };
  }
  const price = s.price;
  const live = (status: string) => status === 'active' || status === 'mitigated';
  const ahead = (low: number, high: number) =>
    side === 'long' ? low >= price && low - price <= atr : high <= price && price - high <= atr;
  const ob = (s.order_blocks ?? []).filter(
    (b) =>
      live(b.status) &&
      b.type === (side === 'long' ? 'bearish_ob' : 'bullish_ob') &&
      ahead(b.bottom, b.top),
  ).length;
  const fvg = (s.fair_value_gaps ?? []).filter(
    (g) =>
      live(g.status) &&
      g.type === (side === 'long' ? 'bearish_fvg' : 'bullish_fvg') &&
      ahead(g.bottom, g.top),
  ).length;
  if (!ob && !fvg) {
    return {
      state: 'لا يوجد',
      explanation: 'لا توجد OB/FVG معاكسة قريبة (ضمن ATR واحد).',
      tone: 'positive',
    };
  }
  return {
    state: `OB ${String(ob)} · FVG ${String(fvg)}`,
    explanation: `مناطق معاكسة قريبة (ضمن ATR واحد): ${String(ob)} OB و${String(fvg)} FVG.`,
    tone: 'negative',
  };
}

function round(n: number): number {
  return Math.round(n * 10) / 10;
}

function buildCategories(
  snapshot: AnalysisSnapshot | null,
  components: ComponentDTO[] | undefined,
  penalties: PenaltyDTO[],
  side: SignalSide | null,
): CategoryRow[] {
  const byName = componentMap(components);
  const ready = snapshot?.analysis_ready ? snapshot : null;
  return CATEGORY_LABELS.map(({ key, label, component }) => {
    const c = component ? byName.get(component) : undefined;
    const points = c ? round(c.points) : null;
    const max = c ? round(c.weight) : null;
    const pens = penalties.filter((p) => (PENALTY_CATEGORY[p.code] ?? 'penalties') === key);
    if (key === 'penalties') {
      const total = penalties.reduce((acc, p) => acc + p.points, 0);
      return {
        key,
        label,
        state: penalties.length ? `−${round(total).toString()}` : 'لا يوجد',
        points: penalties.length ? -round(total) : null,
        max: null,
        explanation: penalties.length
          ? penalties.map((p) => `${p.reason} (−${round(p.points).toString()})`).join('، ')
          : 'لا توجد عقوبات مطبّقة على الإعداد.',
        tone: penalties.length ? 'negative' : 'neutral',
      };
    }
    const base = ready
      ? snapshotRow(key, ready, side)
      : { state: '--', explanation: 'التحليل غير جاهز.', tone: 'neutral' as ExplainTone };
    const penaltyText = pens.length
      ? ` عقوبة: ${pens.map((p) => `${p.reason} (−${round(p.points).toString()})`).join('، ')}.`
      : '';
    const tone: ExplainTone = pens.length ? 'negative' : (ratioTone(points, max) ?? base.tone);
    return {
      key,
      label,
      state: base.state,
      points,
      max,
      explanation: base.explanation + penaltyText,
      tone,
    };
  });
}

/** Everything the panel shows, from one canonical context (snapshot + view already filtered). */
export function explain(
  snapshot: AnalysisSnapshot | null,
  view: SignalView | null,
  strategy: StrategyInfo | null = view?.strategy ?? null,
): Explanation {
  const display = signalDisplay(view);
  const researchOnly = strategy?.signal_capable === false;
  const signal = display.kind === 'confirmed' ? display.signal : null;
  const ev = display.evaluation;
  const hyp = ev?.hypothesis ?? null;
  const bias = analyticalBias(snapshot);

  let decision: Decision;
  if (signal) decision = signal.side === 'long' ? 'BUY' : 'SELL';
  else decision = 'NEUTRAL';

  const side: SignalSide | null =
    signal?.side ??
    hyp?.side ??
    (bias === 'bullish' ? 'long' : bias === 'bearish' ? 'short' : null);
  const components = signal?.components ?? hyp?.components;
  const penalties = signal?.penalties ?? hyp?.penalties ?? [];
  const positives = signal?.positive ?? hyp?.positive ?? [];
  const negatives = signal?.negative ?? hyp?.negative ?? [];

  const ready = snapshot?.analysis_ready ? snapshot : null;
  const trendDir = ready?.trend?.direction ?? null;
  const direction = ready
    ? {
        label: trendDir ? DIRECTION_AR[trendDir] : 'غير متاح',
        detail: `المتوسطات ${trendDir ? DIRECTION_AR[trendDir] : '--'} · الهيكل الرئيسي ${ready.swing_structure ? DIRECTION_AR[ready.swing_structure.direction] : '--'}`,
        tone: trendDir,
      }
    : { label: 'غير متاح', detail: 'التحليل غير جاهز بعد', tone: null };

  const blockers: string[] = [];
  if (!signal) {
    if (strategy && !strategy.signal_capable) {
      blockers.push(OUT_OF_SCOPE_TEXT);
    }
    if (display.kind === 'developing') {
      blockers.push('الإعداد على شمعة لم تُغلق بعد — لا إشارة قبل إغلاقها وتأكيدها.');
    }
    const gate =
      view?.evaluation?.neutral_reason ??
      (display.kind === 'evaluation' ? display.neutralReason : null);
    if (gate) blockers.push(gate);
    if (!view?.evaluation && display.kind !== 'developing' && !researchOnly) {
      blockers.push('بانتظار تقييم الاستراتيجية للشمعة المغلقة التالية.');
    }
    for (const p of penalties) blockers.push(`${p.reason} (−${round(p.points).toString()})`);
    for (const n of negatives) if (!penalties.some((p) => p.reason === n)) blockers.push(n);
  }

  let decisionLabel: string;
  let tradeLine: string;
  let headline: string;
  let reason: string;
  if (signal) {
    decisionLabel = decision === 'BUY' ? 'BUY · شراء' : 'SELL · بيع';
    tradeLine = 'نعم — إشارة مؤكدة';
    headline = 'إشارة مؤكدة — Strategy 4.3';
    reason = [signal.family_ar ?? FAMILY_AR[signal.family], ...positives.slice(0, 2)].join(' · ');
  } else if (researchOnly) {
    decisionLabel = 'محايد';
    tradeLine = 'لا';
    headline = 'لا توجد فرصة تداول مؤكدة حالياً.';
    reason = bias
      ? `${BIAS_AR[bias]} حسب الاتجاه والهيكل — لا توجد فرصة مؤكدة.`
      : 'التحليل غير جاهز بعد.';
  } else {
    decisionLabel = 'محايد';
    tradeLine = 'لا';
    headline = NO_ENTRY_TEXT;
    reason = blockers[0] ?? NO_ENTRY_TEXT;
  }

  const score = signal ? signal.score : hyp ? (ev?.score ?? null) : null;
  return {
    decision,
    decisionLabel,
    tradeLine,
    headline,
    reason,
    direction,
    bias: signal ? null : bias,
    biasLabel: signal || !bias ? null : BIAS_AR[bias],
    score: score !== null && Number.isFinite(score) ? score : null,
    tier: signal?.tier ?? null,
    tierLabel: signal?.tier ? `${signal.tier} — ${signal.tier_ar ?? ''}` : null,
    candidateScore: !signal && score !== null,
    blockers: [...new Set(blockers)],
    positives,
    categories: buildCategories(snapshot, components, penalties, side),
    display,
  };
}

/** Words that must never describe the score. */
export const SCORE_FORBIDDEN = ['نسبة نجاح', 'احتمال نجاح', 'Win probability'];
