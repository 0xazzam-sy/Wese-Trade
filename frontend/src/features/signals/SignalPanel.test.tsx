import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, render as rtlRender, screen, within } from '@testing-library/react';
import type { ReactElement } from 'react';
import { afterEach, describe, expect, it } from 'vitest';

import { useAnalysisStore } from '@/stores/analysisStore';
import { DEFAULT_CHARTS, useChartStore } from '@/stores/chartStore';
import { notReady, readySnapshot } from '@/test/analysisFixture';
import {
  evaluation,
  FORBIDDEN_WORDS,
  FORWARD_STRATEGY,
  PLAN,
  signal,
  view,
} from '@/test/signalFixture';
import type { Timeframe } from '@/types/market';
import { BUY, SELL } from '@/test/frozenSignals';
import type { HypothesisDTO, SignalView } from '@/types/signal';

import { SignalPanel } from './SignalPanel';

afterEach(() => {
  useChartStore.setState({ charts: DEFAULT_CHARTS });
  useAnalysisStore.setState({
    byChart: { primary: null, secondary: null },
    signals: { primary: null, secondary: null },
    executions: { primary: null, secondary: null },
    focused: 'primary',
  });
});

function render(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, enabled: false } } });
  return rtlRender(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

/** The panel only shows data of the chart's canonical context: select it first. */
function select(
  chart: 'primary' | 'secondary',
  data: { symbol: string; timeframe: string } | null,
) {
  if (!data) return;
  const { setSymbol, setTimeframe } = useChartStore.getState();
  setSymbol(chart, data.symbol);
  setTimeframe(chart, data.timeframe as Timeframe);
}

function setPrimary(snapshot: ReturnType<typeof readySnapshot> | null) {
  act(() => {
    select('primary', snapshot);
    useAnalysisStore.getState().setAnalysis('primary', snapshot);
  });
}

const snap15 = (o: Parameters<typeof readySnapshot>[0] = {}) =>
  readySnapshot({ timeframe: '15m', ...o });

function setBoth(snapshot: ReturnType<typeof readySnapshot>, v: SignalView) {
  act(() => {
    select('primary', v);
    useAnalysisStore.getState().setAnalysis('primary', snapshot);
    useAnalysisStore.getState().setSignal('primary', v);
  });
}

const panel = () => screen.getByLabelText('لوحة التحليل');
const category = (key: string) => panel().querySelector(`[data-category="${key}"]`);

const CATEGORY_LABELS = [
  'الاتجاه',
  'الهيكل الرئيسي',
  'الهيكل الداخلي',
  'توافق الفريمات',
  'السيولة',
  'موقع السعر',
  'الزخم',
  'الحجم',
  'التذبذب',
  'الإزاحة',
  'تأكيد الشموع',
  'مناطق معاكسة',
  'العقوبات والموانع',
];

/** A candidate the frozen engine scored but rejected (real neutral payload shape). */
const REJECTED: HypothesisDTO = {
  family: 'TREND_CONTINUATION',
  side: 'long',
  trigger: { id: 't', time: 1, layer: 'internal', type: 'BOS', direction: 'bullish' },
  score: 58.3,
  base_score: 66.3,
  components: [
    { name: 'htf', value: 0.5, weight: 20, points: 10 },
    { name: 'structure', value: 1, weight: 20, points: 20 },
  ],
  penalties: [
    { code: 'opposing_zone_ahead', points: 8, reason: 'منطقة Order Block معاكسة قريبة جداً' },
  ],
  positive: ['الهيكل الرئيسي صاعد'],
  negative: ['منطقة Order Block معاكسة قريبة جداً', 'الزخم ضعيف'],
  regime: 'uptrend',
};

describe('SignalPanel (analysis)', () => {
  it('shows a loading state before the first analysis', () => {
    render(<SignalPanel />);
    expect(screen.getByRole('status')).toHaveTextContent('جاري تحميل التحليل');
    expect(screen.getByTestId('signal-badge')).toHaveTextContent('محايد');
    expect(screen.getByTestId('signal-score')).toHaveTextContent('--');
    expect(screen.getByRole('button', { name: 'تفاصيل الإشارة' })).toBeDisabled();
    expect(screen.queryByTestId('trade-plan')).toBeNull();
  });

  it('shows why analysis is unavailable', () => {
    render(<SignalPanel />);
    setPrimary(notReady('insufficient_history', 'BTCUSDT', '15m'));
    expect(screen.getByRole('status')).toHaveTextContent('بيانات غير كافية للتحليل');
    expect(panel()).toHaveAttribute('data-analysis-state', 'not-ready');
  });

  it('explains every analysis category with real snapshot values', () => {
    render(<SignalPanel />);
    setPrimary(snap15());
    const list = within(screen.getByLabelText('شرح التحليل'));
    for (const label of CATEGORY_LABELS) expect(list.getByText(label)).toBeInTheDocument();
    expect(category('momentum')).toHaveTextContent('RSI 61');
    expect(category('trend')).toHaveTextContent('صاعد');
    expect(screen.getByTestId('decision-direction')).toHaveTextContent('صاعد');
  });

  it('NEUTRAL: no fake trade plan, the strategy sentence and the real gate reason', () => {
    render(<SignalPanel />);
    setBoth(snap15(), view({ evaluation: evaluation() }));
    expect(panel()).toHaveAttribute('data-decision', 'NEUTRAL');
    expect(screen.getByTestId('signal-badge')).toHaveTextContent('محايد');
    expect(screen.getByTestId('decision-headline')).toHaveTextContent('لا توجد فرصة مناسبة حالياً');
    expect(screen.getByTestId('decision-trade')).toHaveTextContent(/^هل في صفقة؟لا$/);
    expect(screen.queryByTestId('trade-plan')).toBeNull();
    for (const abbr of ['Entry', 'SL', 'TP1', 'TP2', 'TP3', 'R:R']) {
      expect(panel().querySelector(`[data-plan="${abbr}"]`)).toBeNull();
    }
    const blockers = screen.getByTestId('entry-blockers');
    expect(blockers).toHaveTextContent('لا توجد فرصة مناسبة حالياً');
    expect(screen.getByTestId('best-opportunity')).toHaveAttribute('data-empty', 'true');
    expect(blockers).toHaveTextContent('لا يوجد محفّز هيكلي على الشمعة الأخيرة');
    expect(screen.getByTestId('signal-state')).toHaveTextContent('لا يوجد محفّز هيكلي');
    expect(screen.getByTestId('signal-score')).toHaveTextContent('--');
  });

  it('NEUTRAL with a rejected candidate: real penalties and reasons, its score labelled', () => {
    render(<SignalPanel />);
    setBoth(
      snap15(),
      view({
        evaluation: evaluation({
          score: 58.3,
          hypothesis: REJECTED,
          neutral_reason: 'قوة الإشارة أقل من حد الاستراتيجية',
        }),
      }),
    );
    const blockers = screen.getByTestId('entry-blockers');
    expect(blockers).toHaveTextContent('قوة الإشارة أقل من حد الاستراتيجية');
    expect(blockers).toHaveTextContent('منطقة Order Block معاكسة قريبة جداً (−8)');
    expect(blockers).toHaveTextContent('الزخم ضعيف');
    expect(screen.getByTestId('signal-score')).toHaveTextContent('58/100');
    expect(screen.getByTestId('candidate-score')).toHaveTextContent('لم يستوفِ شروط الإشارة');
    expect(category('opposing')).toHaveAttribute('data-tone', 'negative');
    expect(category('penalties')).toHaveTextContent('−8');
    expect(category('swing')?.querySelector('[data-testid="category-points"]')).toHaveTextContent(
      '20/20',
    );
    expect(screen.queryByTestId('trade-plan')).toBeNull();
  });

  it('frozen BUY fixture (ETHUSDT 15m): BUY decision, real plan and engine contributions', () => {
    render(<SignalPanel />);
    setBoth(
      snap15({ symbol: 'ETHUSDT' }),
      view({ symbol: 'ETHUSDT', strategy: FORWARD_STRATEGY, active: BUY, lastConfirmed: BUY }),
    );
    expect(panel()).toHaveAttribute('data-decision', 'BUY');
    expect(screen.getByTestId('signal-badge')).toHaveTextContent('BUY · شراء');
    expect(screen.getByTestId('signal-badge')).not.toHaveTextContent('اختبار مباشر');
    expect(screen.getByTestId('signal-score')).toHaveTextContent('81/100');
    expect(panel().querySelector('[data-plan="Entry"]')).toHaveTextContent('2,485.14');
    expect(panel().querySelector('[data-plan="SL"]')).toHaveTextContent('2,467.73');
    expect(panel().querySelector('[data-plan="TP1"]')).toHaveTextContent('2,508.38');
    expect(panel().querySelector('[data-plan="TP2"]')).toHaveTextContent('2,518.31');
    expect(panel().querySelector('[data-plan="TP3"]')).toHaveTextContent('2,558.56');
    expect(screen.queryByTestId('entry-blockers')).toBeNull();
    const pts = (k: string) =>
      category(k)?.querySelector('[data-testid="category-points"]')?.textContent;
    expect(pts('mtf')).toBe('18/20');
    expect(pts('swing')).toBe('20/20');
    expect(pts('liquidity')).toBe('7.5/15');
    expect(pts('trend')).toBe('10/10');
    expect(pts('internal')).toBeUndefined(); // not an engine category: no invented points
    expect(screen.getByTestId('signal-state')).toHaveTextContent('استمرار الاتجاه');
  });

  it('frozen SELL fixture (ETHUSDT 15m): SELL decision with its frozen short plan', () => {
    render(<SignalPanel />);
    setBoth(
      snap15({ symbol: 'ETHUSDT' }),
      view({ symbol: 'ETHUSDT', strategy: FORWARD_STRATEGY, active: SELL, lastConfirmed: SELL }),
    );
    expect(panel()).toHaveAttribute('data-decision', 'SELL');
    expect(screen.getByTestId('signal-badge')).toHaveTextContent('SELL · بيع');
    expect(screen.getByTestId('signal-score')).toHaveTextContent('79/100');
    expect(panel().querySelector('[data-plan="Entry"]')).toHaveTextContent('1,876');
    expect(panel().querySelector('[data-plan="SL"]')).toHaveTextContent('1,889.13');
    expect(panel().querySelector('[data-plan="TP1"]')).toHaveTextContent('1,857.96');
    expect(panel().querySelector('[data-plan="TP2"]')).toHaveTextContent('1,848.16');
    expect(panel().querySelector('[data-plan="TP3"]')).toHaveTextContent('1,835.03');
    expect(panel().textContent).not.toMatch(/STRONG|قوي جداً/);
  });

  it('a developing hypothesis is never shown as a trade', () => {
    render(<SignalPanel />);
    setBoth(
      snap15(),
      view({
        developing: evaluation({
          developing: true,
          signal_class: 'SELL',
          side: 'short',
          score: 80,
          plan: PLAN,
        }),
      }),
    );
    expect(panel()).toHaveAttribute('data-signal-kind', 'developing');
    expect(panel()).toHaveAttribute('data-decision', 'NEUTRAL');
    expect(screen.queryByTestId('trade-plan')).toBeNull();
    expect(screen.getByTestId('entry-blockers')).toHaveTextContent('شمعة لم تُغلق بعد');
  });

  it('a confirmed signal wins over a developing hypothesis', () => {
    render(<SignalPanel />);
    setBoth(
      snap15(),
      view({
        active: signal(),
        developing: evaluation({ developing: true, signal_class: 'SELL', side: 'short' }),
      }),
    );
    expect(screen.getByTestId('signal-badge')).toHaveTextContent('BUY · شراء');
    expect(panel().querySelector('[data-plan="R:R"]')).toHaveTextContent('1.0 / 1.8 / 3.0');
  });

  it('renders a zone entry as a range', () => {
    render(<SignalPanel />);
    const plan = { ...PLAN, entry_model: 'ZONE_ENTRY' as const, entry_low: 99, entry_high: 100.5 };
    setBoth(snap15(), view({ active: signal({ plan, state: 'confirmed', entry_price: null }) }));
    expect(panel().querySelector('[data-plan="Entry"]')?.textContent).toMatch(/99.*–.*100\.5/);
  });

  it('out-of-scope symbol on 15m: neutral, never «تحليل فقط»', () => {
    render(<SignalPanel />);
    setBoth(
      snap15(),
      view({ strategy: { ...FORWARD_STRATEGY, signal_capable: false }, evaluation: evaluation() }),
    );
    expect(panel()).toHaveAttribute('data-decision', 'NEUTRAL');
    expect(screen.getByTestId('signal-badge')).toHaveTextContent('محايد');
    expect(panel()).not.toHaveTextContent('تحليل فقط');
    expect(screen.queryByTestId('trade-plan')).toBeNull();
  });

  it('score wording: strategy-conditions strength, never a success probability', () => {
    render(<SignalPanel />);
    setBoth(snap15(), view({ strategy: FORWARD_STRATEGY, active: signal() }));
    expect(screen.getByTestId('strategy-score')).toHaveTextContent('قوة الإشارة');
    expect(screen.getByTestId('strategy-score')).toHaveAttribute(
      'title',
      'قوة الإشارة تقيس توافق أدلة السوق من 100 وليست احتمال نجاح الصفقة.',
    );
    expect(screen.getByRole('meter', { name: 'قوة الإشارة' })).toHaveAttribute(
      'aria-valuenow',
      '78',
    );
    const text = panel().textContent;
    for (const word of [...FORBIDDEN_WORDS, 'احتمال النجاح', 'Win probability']) {
      expect(text).not.toContain(word);
    }
    expect(text).not.toMatch(/\d\s*%\s*(نجاح|ربح)/);
    expect(screen.getByTestId('strategy-fingerprint')).toHaveTextContent('4.3-6044cea');
    expect(panel()).toHaveTextContent('ليست ضماناً للربح');
  });

  it('opens the details drawer with setup, factors and state', () => {
    render(<SignalPanel />);
    setBoth(snap15(), view({ active: signal() }));
    act(() => {
      screen.getByRole('button', { name: 'تفاصيل الإشارة' }).click();
    });
    const drawer = screen.getByRole('dialog', { name: 'تفاصيل الإشارة' });
    expect(drawer).toHaveTextContent('استمرار الاتجاه');
    expect(drawer).toHaveTextContent('الإطار الأعلى صاعد');
    expect(drawer).toHaveTextContent('78/100');
  });

  it('production wording: Strategy 4.3 reference, no research/experimental labels', () => {
    render(<SignalPanel />);
    setBoth(snap15(), view({ active: signal() }));
    const badge = screen.getByTestId('strategy-status');
    expect(badge).toHaveTextContent('Strategy 4.3');
    const text = panel().textContent;
    for (const w of ['تجريبي', 'غير مُثبت', 'تحليل فقط', 'اختبار مباشر'])
      expect(text).not.toContain(w);
    expect(panel()).toHaveTextContent('ليست ضماناً للربح');
  });

  it('Strategy 4.3: shows «جودة الفرصة» tier and «قوة الإشارة» out of 100', () => {
    render(<SignalPanel />);
    setBoth(
      snap15(),
      view({
        strategy: FORWARD_STRATEGY,
        active: signal({ score: 72, tier: 'B', tier_ar: 'جيدة' }),
      }),
    );
    expect(screen.getByTestId('signal-tier')).toHaveTextContent('جودة الفرصة:B — جيدة');
    expect(screen.getByTestId('signal-score')).toHaveTextContent('72');
    expect(screen.getByTestId('trade-plan')).toBeInTheDocument();
  });

  it('no trade on this timeframe: shows the best opportunity of the symbol and opens it', () => {
    render(<SignalPanel />);
    setBoth(
      snap15(),
      view({
        strategy: FORWARD_STRATEGY,
        evaluation: evaluation(),
        best: {
          id: 'BTCUSDT-1h-x',
          symbol: 'BTCUSDT',
          timeframe: '1h',
          side: 'BUY',
          tier: 'A',
          tier_ar: 'قوية',
          score: 78,
          family: 'TREND_CONTINUATION',
          family_ar: 'استمرار الاتجاه',
          state: 'confirmed',
          state_ar: 'بانتظار الدخول',
          entry: 1,
          stop: 0.9,
          targets: [1.1, 1.2, 1.3],
          rr: [1, 2, 3],
          confirmed_time: 1,
          valid_until: 2,
          regime: 'UPTREND',
          regime_ar: 'اتجاه صاعد',
        },
      }),
    );
    expect(screen.getByTestId('no-trade-line')).toHaveTextContent('لا توجد فرصة مناسبة حالياً');
    const best = screen.getByTestId('best-opportunity');
    expect(best).toHaveTextContent('أفضل فرصة لهذه العملة:');
    expect(best).toHaveTextContent('1h — BUY — A — 78/100');
    act(() => {
      best.click();
    });
    expect(useChartStore.getState().charts.primary.timeframe).toBe('1h');
  });

  it('switches between the primary and secondary chart analysis', () => {
    render(<SignalPanel />);
    setPrimary(snap15());
    act(() => {
      const snap = notReady('loading_history', 'ETHUSDT', '15m');
      select('secondary', snap);
      useAnalysisStore.getState().setAnalysis('secondary', snap);
    });
    act(() => {
      screen.getByRole('radio', { name: 'الثانوي' }).click();
    });
    expect(screen.getByRole('status')).toHaveTextContent('جاري تحميل التحليل');
    expect(screen.getByTestId('analysis-context')).toHaveTextContent('ETHUSDT');
  });
});
