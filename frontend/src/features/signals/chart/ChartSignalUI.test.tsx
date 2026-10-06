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
  it('BUY: «شراء — اختبار مباشر» with Entry/Stop/TP1-3, strength, timeframe, family', () => {
    render(
      <ChartSignalStatus timeframe="15m" open={BUY} strategy={FORWARD_STRATEGY} precision={2} />,
    );
    const status = screen.getByTestId('chart-signal-status');
    expect(status).toHaveAttribute('data-state', 'buy');
    expect(status).toHaveAccessibleName('موقف النظام الآن');
    expect(screen.getByTestId('chart-signal-chip')).toHaveTextContent('شراء — اختبار مباشر');
    for (const v of ['2,485.14', '2,467.73', '2,508.38', '2,518.31', '2,558.56'])
      expect(status).toHaveTextContent(v);
    expect(status).toHaveTextContent('81/100');
    expect(status).toHaveTextContent('غير معايرة');
    expect(status).toHaveTextContent('15m');
    expect(status).toHaveTextContent('استمرار الاتجاه');
    expect(status).toHaveTextContent('غير مُثبت — الإشارة قيد الاختبار وليست توصية مضمونة.');
    noForbiddenWords(status.textContent);
  });

  it('SELL: «بيع — اختبار مباشر» with its plan', () => {
    render(
      <ChartSignalStatus timeframe="15m" open={SELL} strategy={FORWARD_STRATEGY} precision={2} />,
    );
    expect(screen.getByTestId('chart-signal-chip')).toHaveTextContent('بيع — اختبار مباشر');
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
    expect(status).toHaveTextContent('لا توجد فرصة دخول مؤكدة حسب الاستراتيجية حالياً');
    expect(screen.getByTestId('chart-signal-scope')).toHaveTextContent(
      'الإشارات مفعلة على هذا الفريم · اختبار مباشر · غير مُثبت',
    );
  });

  it.each(['1m', '5m', '10m'])('%s: analysis only, signals disabled', (tf) => {
    render(<ChartSignalStatus timeframe={tf} open={null} strategy={FORWARD_STRATEGY} />);
    const status = screen.getByTestId('chart-signal-status');
    expect(status).toHaveAttribute('data-state', 'research');
    expect(status).toHaveTextContent('هذا الفريم للتحليل فقط');
    expect(status).toHaveTextContent('الإشارات غير مفعلة على هذا الفريم');
    expect(status).not.toHaveTextContent('شراء');
    expect(status).not.toHaveTextContent('بيع');
  });

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
    expect(text).toContain('اختبار مباشر');
    expect(text).toContain('ETHUSDT');
    expect(text).toContain('81/100 · غير معايرة');
    expect(text).toContain('Trend Continuation');
    expect(text).toContain('2,485.14');
    expect(text).toContain('2,467.73');
    expect(text).toContain('2,558.56');
    expect(text).toContain('4.2-a03e20f');
    expect(text).toContain('الإشارة قيد الاختبار وليست توصية مضمونة.');
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
