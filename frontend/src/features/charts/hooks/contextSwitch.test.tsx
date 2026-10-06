import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  belongsTo,
  contextualSignal,
  contextualSnapshot,
} from '@/features/analysis/context/chartContext';
import { ChartController } from '@/features/charts/lib/ChartController';
import { marketsApi } from '@/services/api/markets';
import { marketFeed } from '@/services/realtime/marketFeed';
import { readySnapshot } from '@/test/analysisFixture';
import { bar, FakeRealtime } from '@/test/fakeRealtime';
import { view } from '@/test/signalFixture';
import type { CandleList, Timeframe } from '@/types/market';

import { useMarketChart } from './useMarketChart';

/** Prices per symbol: a BTC-scale and several low-price assets. */
const PRICE: Record<string, string> = {
  BTCUSDT: '85960.6',
  ETHUSDT: '2715.4',
  DOGEUSDT: '0.0949',
  NEARUSDT: '5.302',
  PEPEUSDT: '0.00000434',
};

function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

function history(symbol: string, timeframe: Timeframe): CandleList {
  return { symbol, timeframe, candles: [0, 60, 120].map((t) => bar(t, PRICE[symbol], true)) };
}

function makeChart() {
  const series = { setData: vi.fn(), update: vi.fn(), applyOptions: vi.fn() };
  const resetView = vi.fn();
  const controller = new ChartController(series, () => undefined, resetView);
  return { series, resetView, ref: { current: controller } };
}

/** Close price of the last setData call (what the chart actually displays). */
function shownClose(series: { setData: ReturnType<typeof vi.fn> }): number | null {
  const calls = series.setData.mock.calls;
  const data = calls[calls.length - 1]?.[0] as { close: number }[] | undefined;
  return data?.length ? (data[data.length - 1]?.close ?? null) : null;
}

let ws: FakeRealtime;
beforeEach(() => {
  ws = new FakeRealtime();
  marketFeed.attach(ws.asClient());
});
afterEach(() => {
  marketFeed.detach();
  vi.restoreAllMocks();
});

describe('ChartController generations', () => {
  it('every context change restores auto-scale and refuses stale history', () => {
    const { ref, resetView, series } = makeChart();
    const first = ref.current.reset();
    const second = ref.current.reset();
    expect(second).toBe(first + 1);
    expect(resetView).toHaveBeenCalledTimes(2);
    expect(ref.current.setHistory(history('BTCUSDT', '15m').candles, first)).toBe(-1); // stale
    expect(series.setData).toHaveBeenCalledTimes(2); // only the two resets
    expect(ref.current.setHistory(history('NEARUSDT', '15m').candles, second)).toBe(3);
    expect(shownClose(series)).toBe(5.302);
  });
});

describe('canonical chart context', () => {
  const eth5m = { chartId: 'primary' as const, symbol: 'ETHUSDT', timeframe: '5m' as Timeframe };
  it('never accepts analysis or signals of another symbol/timeframe', () => {
    expect(
      contextualSnapshot(readySnapshot({ symbol: 'ADAUSDT', timeframe: '5m' }), eth5m),
    ).toBeNull();
    expect(
      contextualSnapshot(readySnapshot({ symbol: 'ETHUSDT', timeframe: '15m' }), eth5m),
    ).toBeNull();
    expect(
      contextualSnapshot(readySnapshot({ symbol: 'ETHUSDT', timeframe: '5m' }), eth5m),
    ).not.toBeNull();
    expect(contextualSignal(view({ symbol: 'ADAUSDT', timeframe: '5m' }), eth5m)).toBeNull();
    expect(belongsTo(null, eth5m)).toBe(false);
  });
});

describe('rapid symbol/timeframe switching with out-of-order responses', () => {
  it('BTC → ETH → DOGE → NEAR → PEPE → BTC: only the final selection reaches the chart', async () => {
    const pending = new Map<string, ReturnType<typeof deferred<CandleList>>>();
    vi.spyOn(marketsApi, 'candles').mockImplementation((symbol, timeframe) => {
      const d = deferred<CandleList>();
      pending.set(`${symbol}|${timeframe}|${String(pending.size)}`, d);
      void d.promise; // resolved later, in reverse order
      return d.promise.then(() => history(symbol, timeframe));
    });
    const { ref, series, resetView } = makeChart();
    const path: [string, Timeframe][] = [
      ['BTCUSDT', '15m'],
      ['ETHUSDT', '5m'],
      ['DOGEUSDT', '1h'],
      ['NEARUSDT', '1m'],
      ['PEPEUSDT', '30m'],
      ['BTCUSDT', '15m'],
    ];
    const first = path[0] ?? ['BTCUSDT', '15m'];
    const { result, rerender } = renderHook(
      ({ symbol, timeframe }: { symbol: string; timeframe: Timeframe }) =>
        useMarketChart(ref, symbol, timeframe, undefined),
      { initialProps: { symbol: first[0], timeframe: first[1] } },
    );
    for (const [symbol, timeframe] of path.slice(1)) rerender({ symbol, timeframe });
    // resolve every request in REVERSE order (the final one first, stale ones after)
    await act(async () => {
      for (const d of [...pending.values()].reverse()) {
        d.resolve(history('BTCUSDT', '15m'));
        await Promise.resolve();
      }
    });
    await waitFor(() => {
      expect(result.current.load.status).toBe('ready');
    });
    expect(shownClose(series)).toBe(85960.6); // final BTC candles, nothing stale on top
    expect(resetView).toHaveBeenCalledTimes(path.length); // auto-scale restored per switch
    // live subscriptions: exactly one stream left, the final one
    const subs = ws.sent.filter((m) => m.type === 'market.subscribe').length;
    const unsubs = ws.sent.filter((m) => m.type === 'market.unsubscribe').length;
    expect(subs - unsubs).toBe(1);
    expect(ws.sent.filter((m) => m.type === 'market.subscribe').at(-1)?.data).toEqual({
      symbol: 'BTCUSDT',
      timeframe: '15m',
    });
  });

  it('a late response of the previous symbol never overwrites the new one', async () => {
    const btc = deferred<CandleList>();
    const near = deferred<CandleList>();
    vi.spyOn(marketsApi, 'candles').mockImplementation((symbol) =>
      symbol === 'BTCUSDT' ? btc.promise : near.promise,
    );
    const { ref, series } = makeChart();
    const { result, rerender } = renderHook(
      ({ symbol }: { symbol: string }) => useMarketChart(ref, symbol, '15m', undefined),
      { initialProps: { symbol: 'BTCUSDT' } },
    );
    rerender({ symbol: 'NEARUSDT' });
    await act(async () => {
      near.resolve(history('NEARUSDT', '15m'));
      await Promise.resolve();
    });
    await act(async () => {
      btc.resolve(history('BTCUSDT', '15m')); // stale, arrives last
      await Promise.resolve();
    });
    await waitFor(() => {
      expect(result.current.load.status).toBe('ready');
    });
    expect(shownClose(series)).toBe(5.302);
  });

  it('a live candle of the old symbol is never applied to the new chart', async () => {
    vi.spyOn(marketsApi, 'candles').mockImplementation((symbol, timeframe) =>
      Promise.resolve(history(symbol, timeframe)),
    );
    const { ref, series } = makeChart();
    const { result, rerender } = renderHook(
      ({ symbol }: { symbol: string }) => useMarketChart(ref, symbol, '15m', undefined),
      { initialProps: { symbol: 'BTCUSDT' } },
    );
    rerender({ symbol: 'NEARUSDT' });
    await waitFor(() => {
      expect(result.current.load.status).toBe('ready');
    });
    act(() => {
      ws.emit('market.candle', { symbol: 'BTCUSDT', timeframe: '15m', candle: bar(180, '86000') });
    });
    expect(series.update).not.toHaveBeenCalled();
    expect(shownClose(series)).toBe(5.302);
  });
});

describe('two charts switching at the same time stay independent', () => {
  it('each chart ends with its own final selection', async () => {
    vi.spyOn(marketsApi, 'candles').mockImplementation(
      (symbol, timeframe) =>
        new Promise((resolve) => {
          setTimeout(
            () => {
              resolve(history(symbol, timeframe));
            },
            symbol === 'BTCUSDT' ? 30 : 5,
          ); // BTC responses are slower
        }),
    );
    const a = makeChart();
    const b = makeChart();
    const one = renderHook(
      ({ symbol, tf }: { symbol: string; tf: Timeframe }) =>
        useMarketChart(a.ref, symbol, tf, undefined),
      { initialProps: { symbol: 'BTCUSDT', tf: '15m' as Timeframe } },
    );
    const two = renderHook(
      ({ symbol, tf }: { symbol: string; tf: Timeframe }) =>
        useMarketChart(b.ref, symbol, tf, undefined),
      { initialProps: { symbol: 'ETHUSDT', tf: '5m' as Timeframe } },
    );
    one.rerender({ symbol: 'DOGEUSDT', tf: '1h' });
    two.rerender({ symbol: 'BTCUSDT', tf: '1m' });
    one.rerender({ symbol: 'NEARUSDT', tf: '15m' });
    two.rerender({ symbol: 'PEPEUSDT', tf: '30m' });
    await waitFor(() => {
      expect(one.result.current.load.status).toBe('ready');
      expect(two.result.current.load.status).toBe('ready');
    });
    await new Promise((r) => setTimeout(r, 60)); // let every stale response land
    expect(shownClose(a.series)).toBe(5.302);
    expect(shownClose(b.series)).toBe(0.00000434);
  });
});
