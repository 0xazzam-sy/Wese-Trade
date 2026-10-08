import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, render as rtlRender, screen } from '@testing-library/react';
import type { ReactElement } from 'react';
import { afterEach, describe, expect, it } from 'vitest';

import { SignalPanel } from '@/features/signals/SignalPanel';
import { useAnalysisStore } from '@/stores/analysisStore';
import { DEFAULT_CHARTS, useChartStore } from '@/stores/chartStore';
import { readySnapshot } from '@/test/analysisFixture';
import { execState } from '@/test/executionFixture';
import type { ExecutionState } from '@/types/execution';
import type { Timeframe } from '@/types/market';

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

function show(state: ExecutionState | null, timeframe = '5m', symbol = 'ETHUSDT') {
  act(() => {
    const { setSymbol, setTimeframe } = useChartStore.getState();
    setSymbol('primary', symbol);
    setTimeframe('primary', timeframe as Timeframe);
    useAnalysisStore.getState().setAnalysis('primary', readySnapshot({ symbol, timeframe }));
    useAnalysisStore.getState().setExecution('primary', state);
  });
}

const panel = () => screen.getByTestId('execution-panel');

describe('ExecutionPanel (1m / 5m / 10m entry timing)', () => {
  it('15m BUY parent -> 5m BUY confirmation: decision, timing, parent, plan, reasons', () => {
    render(<SignalPanel />);
    show(execState('BUY'));
    expect(panel()).toHaveAttribute('data-decision', 'BUY');
    expect(screen.getByTestId('signal-badge')).toHaveTextContent('BUY — شراء');
    expect(screen.getByTestId('decision-direction')).toHaveTextContent('صاعد');
    expect(screen.getByTestId('decision-timing')).toHaveTextContent('مؤكد');
    expect(screen.getByTestId('decision-parent')).toHaveTextContent('15m Trend Continuation');
    expect(screen.getByTestId('decision-lifecycle')).toHaveTextContent('جاهز للدخول');
    expect(screen.getByTestId('signal-score')).toHaveTextContent('81 / 100');
    expect(screen.getByTestId('score-band')).toHaveTextContent('قوي');
    const plan: [string, string][] = [
      ['Entry', '2,483.9'],
      ['SL', '2,467.73'],
      ['TP1', '2,508.38'],
      ['TP2', '2,518.31'],
      ['TP3', '2,558.56'],
    ];
    for (const [k, v] of plan)
      expect(panel().querySelector(`[data-plan="${k}"]`)).toHaveTextContent(v);
    expect(screen.getByTestId('execution-reasons')).toHaveTextContent('اتجاه 15m صاعد');
    expect(screen.getByTestId('strategy-fingerprint')).toHaveTextContent('Strategy 4.2-a03e20f');
    expect(screen.getByTestId('execution-micro')).toHaveTextContent('سليمة');
  });

  it('WAIT: parent context plan shown as preview, timing not ready, missing evidence listed', () => {
    render(<SignalPanel />);
    show(execState('WAIT', {}, '1m'), '1m');
    expect(screen.getByTestId('signal-badge')).toHaveTextContent('WAIT — انتظر');
    expect(screen.getByTestId('decision-headline')).toHaveTextContent(
      'الصفقة صاعدة لكن توقيت الدخول غير مناسب بعد.',
    );
    expect(screen.getByTestId('trade-plan')).toHaveAttribute('data-preview', 'true');
    expect(screen.getByTestId('execution-cautions')).toHaveTextContent('لا توجد شمعة تأكيد');
    expect(screen.getByTestId('decision-lifecycle')).toHaveTextContent('بانتظار التوقيت');
  });

  it('ENTRY MISSED: never tells the user to chase', () => {
    render(<SignalPanel />);
    show(execState('ENTRY_MISSED', {}, '10m'), '10m');
    expect(screen.getByTestId('signal-badge')).toHaveTextContent('فاتت منطقة الدخول');
    expect(screen.getByTestId('decision-headline')).toHaveTextContent('لا تلاحق السعر');
  });

  it('NO SETUP: no plan, no fabricated BUY/SELL, analysis still described', () => {
    render(<SignalPanel />);
    show(execState('NO_SETUP'));
    expect(screen.getByTestId('signal-badge')).toHaveTextContent('لا توجد فرصة حالية');
    expect(screen.getByTestId('no-setup')).toHaveTextContent('لا توجد فرصة تداول مؤكدة حالياً.');
    expect(screen.queryByTestId('trade-plan')).toBeNull();
    expect(screen.getByTestId('execution-technical')).toHaveTextContent('دعم / مقاومة');
  });

  it('score is a timing strength, never a win probability; no research wording', () => {
    render(<SignalPanel />);
    show(execState('BUY'));
    expect(screen.getByTestId('strategy-score')).toHaveAttribute(
      'title',
      expect.stringContaining('ليست احتمال ربح') as string,
    );
    const text = panel().textContent;
    for (const w of ['تحليل فقط', 'غير مثبت', 'تجريبي', 'احتمال نجاح', 'نسبة نجاح'])
      expect(text).not.toContain(w);
  });

  it('never shows the execution state of another symbol/timeframe (atomic switch)', () => {
    render(<SignalPanel />);
    show(execState('BUY'));
    act(() => {
      useChartStore.getState().setSymbol('primary', 'BTCUSDT'); // switched, late ETH data
    });
    expect(screen.getByTestId('signal-badge')).toHaveTextContent('لا توجد فرصة حالية');
    expect(screen.queryByTestId('trade-plan')).toBeNull();
  });
});
