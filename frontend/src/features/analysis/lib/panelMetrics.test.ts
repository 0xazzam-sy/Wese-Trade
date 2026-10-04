import { describe, expect, it } from 'vitest';

import { must, notReady, readySnapshot } from '@/test/analysisFixture';

import { METRIC_LABELS, panelMetrics } from './panelMetrics';

describe('panelMetrics', () => {
  it('shows "--" for every cell until analysis is ready', () => {
    for (const snapshot of [null, notReady('insufficient_history')]) {
      const cells = panelMetrics(snapshot);
      expect(cells.map((c) => c.label)).toEqual(METRIC_LABELS.map((m) => m.label));
      expect(cells.every((c) => c.value === '--')).toBe(true);
    }
  });

  it('formats backend values in Arabic without computing anything', () => {
    const cells = Object.fromEntries(panelMetrics(readySnapshot()).map((c) => [c.key, c]));
    expect(cells.trend?.value).toBe('صاعد');
    expect(cells.regime?.value).toBe('اتجاه صاعد');
    expect(cells.swing?.value).toBe('صاعد');
    expect(cells.internal?.value).toBe('هابط');
    expect(cells.liquidity?.value).toBe('علوية 3 · سفلية 2');
    expect(cells.volatility?.value).toBe('طبيعي');
    expect(cells.volatility?.detail).toBe('ATR 0.19%');
    expect(cells.momentum?.value).toBe('RSI 61');
    expect(cells.volume?.value).toBe('×2.00');
    expect(cells.volume?.detail).toBe('ارتفاع حاد');
    expect(cells.zone?.value).toBe('منطقة علاوة');
    expect(cells.zone?.tone).toBe('neutral');
  });

  it('labels the last structure event and recent sweeps', () => {
    const base = readySnapshot();
    const swing = {
      ...must(base.swing_structure),
      last_event: must(must(base.swing_structure).events[0]),
    };
    const sweep = {
      id: 's',
      side: 'sell_side' as const,
      pool_id: 'p',
      source: 'swing_low' as const,
      level: 97,
      index: 1,
      time: 9_700,
      confirmed_time: 10_000,
      extreme: 96,
      close: 98,
      penetration: 1,
      penetration_atr: 0.5,
      rejection: 0.7,
      quality: 72.4,
      status: 'confirmed' as const,
      structure_response: null,
      response_time: null,
    };
    const snapshot = readySnapshot({
      swing_structure: swing,
      liquidity: { ...must(base.liquidity), sweeps: [sweep] },
    });
    const cells = Object.fromEntries(panelMetrics(snapshot).map((c) => [c.key, c]));
    expect(cells.swing?.value).toBe('صاعد · BOS');
    expect(cells.liquidity?.value).toBe('سُحبت سيولة سفلية');
    expect(cells.liquidity?.detail).toBe('جودة 72');
  });
});
