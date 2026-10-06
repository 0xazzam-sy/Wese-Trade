import { describe, expect, it } from 'vitest';

import {
  BUY,
  BUY_CANDLES,
  BUY_HISTORY,
  FIXTURE_STRATEGY,
  SELL,
  SELL_HISTORY,
} from '@/test/frozenSignals';
import { FORWARD_STRATEGY, evaluation, signal, STRATEGY, view } from '@/test/signalFixture';

import {
  buildMarkerSpecs,
  chartSignalState,
  isSignalTimeframe,
  mergeChartSignals,
  openSignal,
} from './chartSignals';
import { toSeriesMarkers, withAlpha } from './SignalMarkersOverlay';

// Real engine output (backend/tests/signals/ui_fixtures.py replays the frozen strategy).
const PALETTE = { bull: '#10b981', bear: '#e5484d' };
const at = (iso: string) => Date.parse(iso) / 1000;

describe('deterministic engine fixtures (frozen strategy unchanged)', () => {
  it('BUY: ETHUSDT 15m 2026-09-18 05:00Z, strength 81.15, same plan', () => {
    expect(FIXTURE_STRATEGY).toBe('wese-trade-forward-4.2-a03e20f1d4');
    expect(BUY).toMatchObject({
      symbol: 'ETHUSDT',
      timeframe: '15m',
      side: 'long',
      signal_class: 'BUY',
      family: 'TREND_CONTINUATION',
      trigger_time: at('2026-09-18T05:00:00Z'),
      strategy_version: 'wese-trade-forward-4.2-a03e20f1d4',
    });
    expect(BUY.score).toBeCloseTo(81.15, 2);
    expect(BUY.plan.preferred_entry).toBe(2485.14);
    expect(BUY.plan.stop).toBe(2467.73);
    expect(BUY.plan.targets.map((t) => t.price)).toEqual([2508.38, 2518.31, 2558.56]);
  });

  it('SELL: ETHUSDT 15m 2026-07-31 12:00Z, strength 79.2, same plan', () => {
    expect(SELL).toMatchObject({ side: 'short', signal_class: 'SELL' });
    expect(SELL.trigger_time).toBe(at('2026-07-31T12:00:00Z'));
    expect(SELL.score).toBeCloseTo(79.2, 2);
    expect(SELL.plan.preferred_entry).toBe(1876.0);
    expect(SELL.plan.stop).toBe(1889.13);
    expect(SELL.plan.targets.map((t) => t.price)).toEqual([1857.96, 1848.16, 1835.03]);
  });
});

describe('BUY / SELL markers', () => {
  it('BUY: up arrow below the exact confirmation candle, labelled BUY · شراء', () => {
    const [m] = buildMarkerSpecs([BUY], true);
    expect(m).toEqual({
      id: BUY.id,
      time: at('2026-09-18T05:00:00Z'),
      side: 'long',
      position: 'belowBar',
      shape: 'arrowUp',
      text: 'BUY · شراء',
      active: true,
    });
    const candles = new Set(BUY_CANDLES.map((c) => c.time));
    expect(candles.has(m?.time ?? -1)).toBe(true);
  });

  it('SELL: down arrow above the exact confirmation candle, labelled SELL · بيع', () => {
    const [m] = buildMarkerSpecs([SELL], true);
    expect(m).toMatchObject({
      time: at('2026-07-31T12:00:00Z'),
      position: 'aboveBar',
      shape: 'arrowDown',
      text: 'SELL · بيع',
    });
  });

  it('never draws a NEUTRAL marker (neutral evaluations and developing hypotheses)', () => {
    const neutral = view({
      symbol: 'ETHUSDT',
      evaluation: evaluation({ symbol: 'ETHUSDT', signal_class: 'NEUTRAL' }),
      developing: evaluation({ symbol: 'ETHUSDT', developing: true, signal_class: 'BUY' }),
    });
    expect(mergeChartSignals([], neutral, 'ETHUSDT', '15m')).toEqual([]);
    const fake = { ...BUY, signal_class: 'NEUTRAL' as const };
    expect(mergeChartSignals([fake], null, 'ETHUSDT', '15m')).toEqual([]);
  });

  it('only on candles loaded on the chart', () => {
    expect(buildMarkerSpecs([BUY], true, () => false)).toEqual([]);
    expect(buildMarkerSpecs([BUY], false)).toEqual([]); // layer toggle off
  });

  it('active = full size/colour; closed history stays, muted', () => {
    const merged = mergeChartSignals(BUY_HISTORY, null, 'ETHUSDT', '15m');
    expect(merged.map((s) => s.state)).toEqual(['closed', 'active']);
    const specs = buildMarkerSpecs(merged, true);
    expect(specs.map((s) => s.active)).toEqual([false, true]);
    const [closed, active] = toSeriesMarkers(specs, PALETTE);
    expect(active).toMatchObject({ color: '#10b981', size: 2, shape: 'arrowUp' });
    expect(closed).toMatchObject({ color: 'rgba(16, 185, 129, 0.5)', size: 1.4 });
    expect(openSignal(merged)?.id).toBe(BUY.id);
    const stopped = mergeChartSignals(SELL_HISTORY, null, 'ETHUSDT', '15m');
    expect(stopped[0]?.state).toBe('stopped');
    expect(openSignal(stopped)).toBeNull(); // no trade-plan lines for a closed signal
    expect(buildMarkerSpecs(stopped, true)[0]?.active).toBe(false);
  });

  it('withAlpha keeps non-hex colours unchanged', () => {
    expect(withAlpha('#e5484d', 0.5)).toBe('rgba(229, 72, 77, 0.5)');
    expect(withAlpha('rgb(1 2 3)', 0.5)).toBe('rgb(1 2 3)');
  });
});

describe('signal timeframes', () => {
  const at15 = { ...BUY };
  it.each(['15m', '30m', '1h'])('%s shows directional markers', (tf) => {
    const s = { ...at15, timeframe: tf };
    expect(isSignalTimeframe(tf)).toBe(true);
    expect(buildMarkerSpecs(mergeChartSignals([s], null, 'ETHUSDT', tf), true)).toHaveLength(1);
    expect(chartSignalState(tf, s, FORWARD_STRATEGY)).toBe('buy');
  });

  it.each(['1m', '5m', '10m'])('%s is analysis-only: never a BUY/SELL marker', (tf) => {
    const s = { ...at15, timeframe: tf };
    const live = view({ symbol: 'ETHUSDT', timeframe: tf, active: s, lastConfirmed: s });
    expect(isSignalTimeframe(tf)).toBe(false);
    expect(mergeChartSignals([s], live, 'ETHUSDT', tf)).toEqual([]);
    expect(chartSignalState(tf, null, FORWARD_STRATEGY)).toBe('research');
  });
});

describe('status state', () => {
  it('BUY / SELL only from an open confirmed signal, otherwise neutral', () => {
    expect(chartSignalState('15m', BUY, FORWARD_STRATEGY)).toBe('buy');
    expect(chartSignalState('15m', SELL, FORWARD_STRATEGY)).toBe('sell');
    expect(chartSignalState('15m', null, FORWARD_STRATEGY)).toBe('neutral');
    expect(chartSignalState('15m', null, null)).toBe('neutral');
    expect(chartSignalState('15m', null, { ...STRATEGY, signal_capable: false })).toBe('paused');
  });
});

describe('merge: persistence + live, no duplicates, no cross-chart leakage', () => {
  it('restores persisted signals (restart) and keeps one marker per signal id', () => {
    const live = view({ symbol: 'ETHUSDT', active: BUY, lastConfirmed: BUY });
    const merged = mergeChartSignals([BUY, BUY], live, 'ETHUSDT', '15m');
    expect(merged.map((s) => s.id)).toEqual([BUY.id]);
  });

  it('the most recent lifecycle state wins (live update after a stale history)', () => {
    const later = { ...BUY, state: 'stopped' as const, state_time: BUY.state_time + 900 };
    const live = view({ symbol: 'ETHUSDT', lastClosed: later });
    expect(mergeChartSignals([BUY], live, 'ETHUSDT', '15m')).toEqual([later]);
    // an older live copy never overrides newer persisted state
    const stale = view({ symbol: 'ETHUSDT', active: BUY });
    expect(mergeChartSignals([later], stale, 'ETHUSDT', '15m')).toEqual([later]);
  });

  it('ignores another symbol / timeframe (two charts stay independent)', () => {
    const other = signal({ id: 'btc', symbol: 'BTCUSDT', timeframe: '15m' });
    const otherView = view({ symbol: 'BTCUSDT', active: other, lastConfirmed: other });
    expect(mergeChartSignals([other], otherView, 'ETHUSDT', '15m')).toEqual([]);
    expect(mergeChartSignals([BUY], null, 'ETHUSDT', '1h')).toEqual([]);
    expect(mergeChartSignals([BUY], null, 'ETHUSDT', '15m')).toHaveLength(1);
  });
});
