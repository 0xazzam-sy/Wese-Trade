import { describe, expect, it } from 'vitest';

import { must, notReady, readySnapshot } from '@/test/analysisFixture';

import { applyAnalysisUpdate } from './merge';

const BTC5 = { symbol: 'BTCUSDT', timeframe: '5m' };

describe('applyAnalysisUpdate', () => {
  it('full snapshots replace the current one', () => {
    const full = readySnapshot();
    expect(applyAnalysisUpdate(null, full, BTC5)).toBe(full);
    expect(applyAnalysisUpdate(full, notReady('loading_history'), BTC5)?.analysis_ready).toBe(
      false,
    );
  });

  it('merges a live update onto the full snapshot of the same candle', () => {
    const full = readySnapshot();
    const live = {
      ...notReady('x'),
      kind: 'live' as const,
      analysis_ready: true,
      reason: null,
      candle_time: full.candle_time,
      forming_time: 10_300,
      price: 106.5,
      developing: { ...must(full.developing), sweeps: [] },
      premium_discount: { ...must(full.premium_discount), position: 70 },
      ote: null,
    };
    const merged = applyAnalysisUpdate(full, live, BTC5);
    expect(merged?.price).toBe(106.5);
    expect(merged?.premium_discount?.position).toBe(70);
    expect(merged?.swing_structure).toBe(full.swing_structure); // confirmed parts kept
  });

  it('ignores stale live updates and late updates for another stream', () => {
    const full = readySnapshot();
    const staleLive = { ...readySnapshot(), kind: 'live' as const, candle_time: 9_700, price: 1 };
    expect(applyAnalysisUpdate(full, staleLive, BTC5)).toBe(full);
    expect(applyAnalysisUpdate(null, staleLive, BTC5)).toBeNull();
    const eth = readySnapshot({ symbol: 'ETHUSDT' });
    expect(applyAnalysisUpdate(full, eth, BTC5)).toBe(full);
    const otherTf = readySnapshot({ timeframe: '1m' });
    expect(applyAnalysisUpdate(full, otherTf, BTC5)).toBe(full);
    const olderFull = readySnapshot({ candle_time: 9_000 });
    expect(applyAnalysisUpdate(full, olderFull, BTC5)).toBe(full);
  });
});
