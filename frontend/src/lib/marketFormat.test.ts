import { describe, expect, it } from 'vitest';

import { changePercent, direction, formatPercent, formatPrice } from './marketFormat';

describe('market formatting', () => {
  it('formats 24h change with sign and two decimals', () => {
    expect(formatPercent(1.234)).toBe('+1.23%');
    expect(formatPercent(-0.5)).toBe('-0.50%');
    expect(formatPercent(0.001)).toBe('0.00%');
    expect(formatPercent(null)).toBe('--');
  });

  it('classifies direction (neutral when zero)', () => {
    expect(direction(0.31)).toBe('up');
    expect(direction(-0.62)).toBe('down');
    expect(direction(0)).toBe('flat');
    expect(direction(null)).toBe('flat');
  });

  it('computes live 24h change from the 24h open, falling back to the ticker value', () => {
    expect(changePercent('110', '100', '5')).toBeCloseTo(10);
    expect(changePercent(null, '100', '0.31')).toBeCloseTo(0.31);
    expect(changePercent(null, null, null)).toBeNull();
  });

  it('formats prices with exchange precision and placeholders', () => {
    expect(formatPrice('65000.5', 1)).toBe('65,000.5');
    expect(formatPrice('0.01612', 5)).toBe('0.01612');
    expect(formatPrice(null)).toBe('--');
  });
});
