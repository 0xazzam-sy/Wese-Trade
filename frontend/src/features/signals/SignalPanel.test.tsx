import { act, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { useAnalysisStore } from '@/stores/analysisStore';
import { notReady, readySnapshot } from '@/test/analysisFixture';

import { SignalPanel } from './SignalPanel';

afterEach(() => {
  useAnalysisStore.setState({ byChart: { primary: null, secondary: null }, focused: 'primary' });
});

function setPrimary(snapshot: ReturnType<typeof readySnapshot> | null) {
  act(() => {
    useAnalysisStore.getState().setAnalysis('primary', snapshot);
  });
}

describe('SignalPanel (analysis)', () => {
  it('shows a loading state before the first analysis', () => {
    render(<SignalPanel />);
    expect(screen.getByRole('status')).toHaveTextContent('جاري تحميل التحليل');
    const cells = within(screen.getByLabelText('مؤشرات التحليل'));
    expect(cells.getAllByText('--')).toHaveLength(9);
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

  it('never shows a BUY/SELL label or an Entry/SL/TP value', () => {
    render(<SignalPanel />);
    setPrimary(readySnapshot());
    const panel = screen.getByLabelText('لوحة التحليل');
    expect(panel.textContent).not.toMatch(/\b(BUY|SELL|STRONG)\b/);
    // Whole words only ("طبيعي" = normal contains the letters of "بيع").
    const words = panel.textContent.split(/[\s·]+/);
    expect(words).not.toContain('شراء');
    expect(words).not.toContain('بيع');
    expect(within(panel).getByText('لا توجد إشارة حالياً')).toBeInTheDocument();
    for (const label of [
      'سعر الدخول',
      'وقف الخسارة',
      'الهدف الأول',
      'الهدف الثاني',
      'الهدف الثالث',
    ]) {
      const cell = within(panel).getByText(label).closest('div');
      expect(cell).toHaveTextContent('--');
      expect(cell?.getAttribute('title')).toContain('غير متاح بعد');
    }
  });

  it('switches between the primary and secondary chart analysis', () => {
    render(<SignalPanel />);
    setPrimary(readySnapshot());
    act(() => {
      useAnalysisStore.getState().setAnalysis('secondary', notReady('loading_history', 'ETHUSDT'));
    });
    act(() => {
      screen.getByRole('radio', { name: 'الثانوي' }).click();
    });
    expect(screen.getByRole('status')).toHaveTextContent('جاري تحميل التحليل');
  });
});
