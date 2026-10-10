import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { BUY, SELL } from '@/test/frozenSignals';
import { FORBIDDEN_WORDS, FORWARD_STRATEGY } from '@/test/signalFixture';

import { ChartLegend } from './ChartLegend';
import { ChartSignalStatus } from './ChartSignalStatus';
import { CHART_SIGNAL_AR, LEGEND_TERMS } from './copy';
import { SignalMarkerCard } from './SignalMarkerCard';

function noForbiddenWords(text: string) {
  for (const word of FORBIDDEN_WORDS) expect(text).not.toContain(word);
  expect(text).not.toMatch(/احتمال|نسبة النجاح|%/);
}

describe('ChartSignalStatus («شو موقف النظام هلق؟»)', () => {
  it('BUY: «BUY — شراء» with Entry/Stop/TP1-3, strength, timeframe, family', () => {
    render(
      <ChartSignalStatus timeframe="15m" open={BUY} strategy={FORWARD_STRATEGY} precision={2} />,
    );
    const status = screen.getByTestId('chart-signal-status');
    expect(status).toHaveAttribute('data-state', 'buy');
    expect(status).toHaveAccessibleName('موقف النظام الآن');
    expect(screen.getByTestId('chart-signal-chip')).toHaveTextContent('BUY — شراء');
    for (const v of ['2,485.14', '2,467.73', '2,508.38', '2,518.31', '2,558.56'])
      expect(status).toHaveTextContent(v);
    expect(status).toHaveTextContent('81/100');
    expect(status).toHaveTextContent('غير معايرة');
    expect(status).toHaveTextContent('15m');
    expect(status).toHaveTextContent('استمرار الاتجاه');
    expect(status).toHaveTextContent('الإشارة تحليلية وليست توصية مضمونة.');
    expect(status).not.toHaveTextContent('اختبار مباشر');
    expect(status).not.toHaveTextContent('تجريبي');
    noForbiddenWords(status.textContent);
  });

  it('SELL: «SELL — بيع» with its plan', () => {
    render(
      <ChartSignalStatus timeframe="15m" open={SELL} strategy={FORWARD_STRATEGY} precision={2} />,
    );
    expect(screen.getByTestId('chart-signal-chip')).toHaveTextContent('SELL — بيع');
    const status = screen.getByTestId('chart-signal-status');
    expect(status).toHaveAttribute('data-state', 'sell');
    for (const v of ['1,876.00', '1,889.13', '1,857.96', '1,848.16', '1,835.03'])
      expect(status).toHaveTextContent(v);
  });

  it('NEUTRAL: «محايد» + no confirmed entry; signals enabled on this timeframe', () => {
    render(<ChartSignalStatus timeframe="30m" open={null} strategy={FORWARD_STRATEGY} />);
    const status = screen.getByTestId('chart-signal-status');
    expect(status).toHaveAttribute('data-state', 'neutral');
    expect(screen.getByTestId('chart-signal-chip')).toHaveTextContent(/^محايد$/);
    expect(status).toHaveTextContent('لا توجد فرصة مناسبة حالياً');
    expect(screen.getByTestId('chart-signal-scope')).toHaveTextContent('Strategy 4.3');
  });

  it.each(['1m', '5m', '10m'])(
    '%s: never a Strategy 4.3 signal (execution layer instead)',
    (tf) => {
      render(<ChartSignalStatus timeframe={tf} open={null} strategy={FORWARD_STRATEGY} />);
      const status = screen.getByTestId('chart-signal-status');
      expect(status).toHaveAttribute('data-state', 'research');
      expect(status).not.toHaveTextContent('تحليل فقط');
      expect(status).not.toHaveTextContent('شراء');
      expect(status).not.toHaveTextContent('بيع');
    },
  );

  it('1h is signal-enabled', () => {
    render(<ChartSignalStatus timeframe="1h" open={null} strategy={FORWARD_STRATEGY} />);
    expect(screen.getByTestId('chart-signal-scope')).toHaveTextContent(CHART_SIGNAL_AR.enabled);
  });
});

describe('SignalMarkerCard (marker tooltip)', () => {
  it('shows every required field; score is a strength, never a probability', () => {
    render(<SignalMarkerCard signal={BUY} x={100} y={80} precision={2} />);
    const card = screen.getByTestId('signal-marker-card');
    const text = card.textContent;
    for (const label of [
      'نوع الإشارة',
      'الحالة',
      'الوقت',
      'الرمز',
      'الفريم',
      'قوة الإشارة',
      'الاستراتيجية',
      'Entry',
      'Stop Loss',
      'TP1',
      'TP2',
      'TP3',
      'Risk/Reward',
      'Strategy fingerprint',
    ])
      expect(text).toContain(label);
    expect(text).toContain('شراء BUY');
    expect(text).toContain('Strategy 4.3');
    expect(text).toContain('ETHUSDT');
    expect(text).toContain('81/100 · غير معايرة');
    expect(text).toContain('2,485.14');
    expect(text).toContain('2,467.73');
    expect(text).toContain('2,558.56');
    expect(text).toContain('4.2-a03e20f');
    expect(text).toContain('الإشارة تحليلية وليست توصية مضمونة.');
    noForbiddenWords(text);
  });

  it('SELL card, kept inside the window', () => {
    render(<SignalMarkerCard signal={SELL} x={window.innerWidth - 10} y={10} />);
    const card = screen.getByTestId('signal-marker-card');
    expect(card.textContent).toContain('بيع SELL');
    expect(Number.parseFloat(card.style.left) + 300).toBeLessThanOrEqual(window.innerWidth);
  });
});

describe('ChartLegend («شرح الشارت»)', () => {
  it('opens an RTL dialog explaining every term and who decides BUY/SELL', () => {
    render(<ChartLegend />);
    expect(screen.queryByRole('dialog')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'شرح الشارت' }));
    const dialog = screen.getByRole('dialog', { name: 'شرح الشارت' });
    expect(dialog).toHaveAttribute('dir', 'rtl');
    expect(within(dialog).getByTestId('legend-authority')).toHaveTextContent(
      'هذه العلامات تشرح تحليل السوق فقط. قرار BUY أو SELL يصدر حصراً من محرك إشارات Wese Trade.',
    );
    for (const { term, ar } of LEGEND_TERMS) {
      expect(within(dialog).getByText(term)).toBeInTheDocument();
      expect(within(dialog).getByText(ar)).toBeInTheDocument();
    }
    expect(dialog).toHaveTextContent('قمة أعلى');
    expect(dialog).toHaveTextContent('سحب سيولة');
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).toBeNull();
  });
});
