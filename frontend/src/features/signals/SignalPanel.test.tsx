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
  STRATEGY,
  view,
} from '@/test/signalFixture';
import type { Timeframe } from '@/types/market';
import type { SignalView, TradePlanDTO } from '@/types/signal';

import { SignalPanel } from './SignalPanel';

afterEach(() => {
  useChartStore.setState({ charts: DEFAULT_CHARTS });
  useAnalysisStore.setState({
    byChart: { primary: null, secondary: null },
    signals: { primary: null, secondary: null },
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

function setSignal(v: SignalView | null) {
  act(() => {
    select('primary', v);
    useAnalysisStore.getState().setSignal('primary', v);
  });
}

function setPrimary(snapshot: ReturnType<typeof readySnapshot> | null) {
  act(() => {
    select('primary', snapshot);
    useAnalysisStore.getState().setAnalysis('primary', snapshot);
  });
}

describe('SignalPanel (analysis)', () => {
  it('shows a loading state before the first analysis', () => {
    render(<SignalPanel />);
    expect(screen.getByRole('status')).toHaveTextContent('جاري تحميل التحليل');
    const cells = within(screen.getByLabelText('مؤشرات التحليل'));
    expect(cells.getAllByText('--')).toHaveLength(9);
    expect(screen.getByRole('button', { name: 'تفاصيل الإشارة' })).toBeDisabled();
  });

  it('shows why analysis is unavailable', () => {
    render(<SignalPanel />);
    setPrimary(notReady('insufficient_history'));
    expect(screen.getByRole('status')).toHaveTextContent('بيانات غير كافية للتحليل');
    expect(screen.getByLabelText('لوحة التحليل')).toHaveAttribute(
      'data-analysis-state',
      'not-ready',
    );
  });

  it('renders real analysis values and the MTF panel', () => {
    render(<SignalPanel />);
    setPrimary(readySnapshot());
    const panel = screen.getByLabelText('لوحة التحليل');
    expect(panel).toHaveAttribute('data-analysis-state', 'ready');
    expect(screen.queryByRole('status')).toBeNull();
    for (const label of [
      'الاتجاه',
      'حالة السوق',
      'الهيكل الرئيسي',
      'الهيكل الداخلي',
      'السيولة',
      'التذبذب',
      'الزخم',
      'الحجم',
      'المنطقة الحالية',
    ]) {
      expect(within(panel).getByText(label)).toBeInTheDocument();
    }
    expect(within(panel).getByText('RSI 61')).toBeInTheDocument();
    const mtf = screen.getByLabelText('السياق متعدد الأطر');
    expect(within(mtf).getByText('5د')).toBeInTheDocument();
    expect(within(mtf).getByText('15د')).toBeInTheDocument();
    expect(within(mtf).getByText('1س')).toBeInTheDocument();
    expect(within(mtf).getByText('محايد')).toBeInTheDocument();
    expect(within(mtf).getByText('توافق صاعد')).toBeInTheDocument();
  });

  it('shows no signal and empty plan cells without a signal', () => {
    render(<SignalPanel />);
    setPrimary(readySnapshot());
    const panel = screen.getByLabelText('لوحة التحليل');
    expect(panel).toHaveAttribute('data-signal-kind', 'none');
    expect(screen.getByTestId('signal-badge')).toHaveTextContent('لا توجد إشارة حالياً');
    for (const abbr of ['Entry', 'SL', 'TP1', 'TP2', 'TP3', 'R:R']) {
      const cell = panel.querySelector(`[data-plan="${abbr}"]`);
      expect(cell).toHaveTextContent('--');
    }
    expect(screen.getByTestId('signal-score')).toHaveTextContent('--');
  });

  it('shows a confirmed signal: class, score out of 100, and the backend trade plan', () => {
    render(<SignalPanel />);
    setPrimary(readySnapshot());
    setSignal(view({ active: signal(), lastConfirmed: signal() }));
    const panel = screen.getByLabelText('لوحة التحليل');
    expect(panel).toHaveAttribute('data-signal-kind', 'confirmed');
    expect(panel).toHaveAttribute('data-signal-class', 'BUY');
    expect(screen.getByTestId('signal-badge')).toHaveTextContent('شراء');
    expect(screen.getByTestId('signal-score')).toHaveTextContent('78/100');
    expect(screen.getByRole('meter', { name: 'قوة الإشارة' })).toHaveAttribute(
      'aria-valuenow',
      '78',
    );
    expect(panel.querySelector('[data-plan="SL"]')).toHaveTextContent('98');
    expect(panel.querySelector('[data-plan="TP3"]')).toHaveTextContent('106');
    expect(panel.querySelector('[data-plan="R:R"]')).toHaveTextContent('1.0 / 1.8 / 3.0');
    expect(screen.getByTestId('signal-state')).toHaveTextContent('نشطة');
    // The score is confluence, never a probability.
    const signalBlock = screen.getByTestId('signal-score').closest('div')?.parentElement;
    expect(signalBlock?.textContent).not.toMatch(/\d\s*%/);
    expect(panel.textContent).not.toContain('احتمال النجاح');
    expect(panel).toHaveTextContent('الإشارات تحليلية وليست ضماناً للربح.');
  });

  it('renders a zone entry as a range', () => {
    render(<SignalPanel />);
    setPrimary(readySnapshot());
    const plan = { ...PLAN, entry_model: 'ZONE_ENTRY' as const, entry_low: 99, entry_high: 100.5 };
    setSignal(view({ active: signal({ plan, state: 'confirmed', entry_price: null }) }));
    const cell = screen.getByLabelText('لوحة التحليل').querySelector('[data-plan="Entry"]');
    expect(cell?.textContent).toMatch(/99.*–.*100\.5/);
  });

  it('marks a developing hypothesis as not confirmed', () => {
    render(<SignalPanel />);
    setPrimary(readySnapshot());
    setSignal(
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
    const panel = screen.getByLabelText('لوحة التحليل');
    expect(panel).toHaveAttribute('data-signal-kind', 'developing');
    expect(screen.getByTestId('signal-badge')).toHaveTextContent('بيع — قيد التشكّل');
    expect(screen.getByTestId('signal-state')).toHaveTextContent('ليست إشارة مؤكدة');
  });

  it('a confirmed signal wins over a developing hypothesis', () => {
    render(<SignalPanel />);
    setPrimary(readySnapshot());
    setSignal(
      view({
        active: signal(),
        developing: evaluation({ developing: true, signal_class: 'SELL', side: 'short' }),
      }),
    );
    expect(screen.getByTestId('signal-badge')).toHaveTextContent(/^شراء$/);
  });

  it('shows NEUTRAL with its reason and no score', () => {
    render(<SignalPanel />);
    setPrimary(readySnapshot());
    setSignal(view({ evaluation: evaluation() }));
    expect(screen.getByTestId('signal-badge')).toHaveTextContent('محايد');
    expect(screen.getByTestId('signal-score')).toHaveTextContent('--');
    expect(screen.getByTestId('signal-state')).toHaveTextContent('لا يوجد محفّز');
  });

  it('opens the details drawer with setup, factors and state', () => {
    render(<SignalPanel />);
    setPrimary(readySnapshot());
    setSignal(view({ active: signal() }));
    act(() => {
      screen.getByRole('button', { name: 'تفاصيل الإشارة' }).click();
    });
    const drawer = screen.getByRole('dialog', { name: 'تفاصيل الإشارة' });
    expect(drawer).toHaveTextContent('استمرار الاتجاه');
    expect(drawer).toHaveTextContent('الإطار الأعلى صاعد');
    expect(drawer).toHaveTextContent('الحجم أقل من المتوسط');
    expect(drawer).toHaveTextContent('78/100');
  });

  it('labels the unproven baseline as experimental, never as proven', () => {
    render(<SignalPanel />);
    setPrimary(readySnapshot());
    setSignal(view({ active: signal() }));
    const badge = screen.getByTestId('strategy-status');
    expect(badge).toHaveAttribute('data-status', 'unproven');
    expect(badge).toHaveTextContent('تجريبي · غير مُثبت');
    expect(screen.getByLabelText('لوحة التحليل')).toHaveTextContent('ليست توصية');
    expect(screen.queryByTestId('research-only')).toBeNull();
  });

  it('shows the forward-test badge for a forward-tested strategy', () => {
    render(<SignalPanel />);
    setPrimary(readySnapshot());
    setSignal(
      view({
        strategy: {
          ...STRATEGY,
          status: 'forward_test',
          status_ar: 'اختبار مباشر',
          forward_test: true,
        },
        active: signal(),
      }),
    );
    const badge = screen.getByTestId('strategy-status');
    expect(badge).toHaveTextContent('اختبار مباشر');
    expect(badge).toHaveAttribute('data-status', 'forward_test');
  });

  it('marks research-only timeframes as not enabled for signals', () => {
    render(<SignalPanel />);
    setPrimary(readySnapshot());
    setSignal(view({ strategy: { ...STRATEGY, signal_capable: false }, evaluation: evaluation() }));
    expect(screen.getByTestId('research-only')).toHaveTextContent(
      'هذا الفريم غير مفعّل للإشارات حالياً',
    );
    expect(screen.getByTestId('signal-badge')).toHaveTextContent('محايد');
  });

  it('labels a forward-test BUY, shows the fingerprint and an uncalibrated score', () => {
    render(<SignalPanel />);
    setPrimary(readySnapshot());
    setSignal(view({ strategy: FORWARD_STRATEGY, active: signal() }));
    expect(screen.getByTestId('signal-badge')).toHaveTextContent('شراء — اختبار مباشر');
    expect(screen.getByTestId('strategy-status')).toHaveTextContent('اختبار مباشر');
    expect(screen.getByTestId('strategy-fingerprint')).toHaveTextContent('4.2-a03e20f');
    expect(screen.getByTestId('score-uncalibrated')).toHaveTextContent('غير معايرة');
    expect(screen.getByTestId('strategy-note')).toHaveTextContent(
      'الإشارات قيد الاختبار وليست توصيات مضمونة.',
    );
    const text = screen.getByLabelText('لوحة التحليل').textContent;
    for (const word of FORBIDDEN_WORDS) expect(text).not.toContain(word);
  });

  it('renders a forward-test SELL with its frozen short plan (values from the real ETH fixture)', () => {
    render(<SignalPanel />);
    setPrimary(readySnapshot());
    const shortPlan: TradePlanDTO = {
      entry_model: 'ZONE_ENTRY',
      entry_low: 1876.0,
      entry_high: 1880.2,
      preferred_entry: 1876.0,
      stop: 1889.13,
      invalidation: 1889.13,
      stop_source: 'swing_high',
      risk: 13.13,
      risk_atr: 1,
      targets: [
        { price: 1857.96, rr: 1.37, source: 'liquidity' },
        { price: 1848.16, rr: 2.12, source: 'swing_low' },
        { price: 1835.03, rr: 3.12, source: 'extension' },
      ],
      rr: [1.37, 2.12, 3.12],
    };
    const sell = signal({
      side: 'short',
      signal_class: 'SELL',
      score: 79.2,
      plan: shortPlan,
      state: 'confirmed',
      positive: ['الإطار الأعلى هابط'],
      negative: ['زخم ضعيف'],
      strategy_version: 'wese-trade-forward-4.2-a03e20f1d4',
    });
    setSignal(view({ strategy: FORWARD_STRATEGY, active: sell, lastConfirmed: sell }));
    const panel = screen.getByLabelText('لوحة التحليل');
    expect(panel).toHaveAttribute('data-signal-class', 'SELL');
    expect(screen.getByTestId('signal-badge')).toHaveTextContent('بيع — اختبار مباشر');
    expect(screen.getByTestId('signal-score')).toHaveTextContent('79/100');
    expect(panel.querySelector('[data-plan="SL"]')).toHaveTextContent('1,889.13');
    expect(panel.querySelector('[data-plan="TP1"]')).toHaveTextContent('1,857.96');
    expect(panel.querySelector('[data-plan="TP3"]')).toHaveTextContent('1,835.03');
    expect(panel.querySelector('[data-plan="R:R"]')).toHaveTextContent('1.4 / 2.1 / 3.1');
    expect(screen.getByTestId('score-uncalibrated')).toHaveTextContent('غير معايرة');
    expect(panel.textContent).not.toMatch(/STRONG|قوي جداً/);
  });

  it('shows the forward-test scope note on 1m/5m/10m', () => {
    render(<SignalPanel />);
    setPrimary(readySnapshot());
    setSignal(
      view({
        timeframe: '5m',
        strategy: {
          ...FORWARD_STRATEGY,
          signal_capable: false,
          scope_note_ar: 'هذا الفريم غير مفعّل للإشارات حالياً',
        },
        evaluation: evaluation(),
      }),
    );
    expect(screen.getByTestId('research-only')).toHaveTextContent(
      'هذا الفريم غير مفعّل للإشارات حالياً',
    );
    expect(screen.getByTestId('signal-badge')).not.toHaveTextContent('شراء');
  });

  it('switches between the primary and secondary chart analysis', () => {
    render(<SignalPanel />);
    setPrimary(readySnapshot());
    act(() => {
      const snap = notReady('loading_history', 'ETHUSDT');
      select('secondary', snap);
      useAnalysisStore.getState().setAnalysis('secondary', snap);
    });
    act(() => {
      screen.getByRole('radio', { name: 'الثانوي' }).click();
    });
    expect(screen.getByRole('status')).toHaveTextContent('جاري تحميل التحليل');
  });
});
