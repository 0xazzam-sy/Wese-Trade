import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ChartController } from '@/features/charts/lib/ChartController';
import { ApiError } from '@/lib/http';
import { marketsApi } from '@/services/api/markets';
import { marketFeed } from '@/services/realtime/marketFeed';
import { bar, FakeRealtime } from '@/test/fakeRealtime';
import type { CandleList, Timeframe } from '@/types/market';

import { useMarketChart } from './useMarketChart';

function makeChart() {
  const series = { setData: vi.fn(), update: vi.fn(), applyOptions: vi.fn() };
  const controller = new ChartController(series);
  return { series, ref: { current: controller } };
}

function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const history = (symbol: string, timeframe: Timeframe, times: number[]): CandleList => ({
  symbol,
  timeframe,
  candles: times.map((t) => bar(t, '100', true)),
});

let ws: FakeRealtime;

beforeEach(() => {
  ws = new FakeRealtime();
  marketFeed.attach(ws.asClient());
});

afterEach(() => {
  marketFeed.detach();
});

describe('useMarketChart', () => {
  it('loads history, buffers early live bars, then applies live updates', async () => {
    const pending = deferred<CandleList>();
    vi.spyOn(marketsApi, 'candles').mockReturnValue(pending.promise);
    const { ref, series } = makeChart();
    const { result } = renderHook(() => useMarketChart(ref, 'BTCUSDT', '1m', undefined));
    expect(result.current.load.status).toBe('loading');
    expect(ws.sent).toContainEqual({
      type: 'market.subscribe',
      data: { symbol: 'BTCUSDT', timeframe: '1m' },
    });

    // A live bar arrives before history: buffered, not applied.
    ws.emit('market.candle', { symbol: 'BTCUSDT', timeframe: '1m', candle: bar(180, '120') });
    expect(series.update).not.toHaveBeenCalled();

    await act(async () => {
      pending.resolve(history('BTCUSDT', '1m', [60, 120, 180]));
      await pending.promise;
    });
    expect(result.current.load).toEqual({ status: 'ready', empty: false });
    expect(series.update).toHaveBeenCalledWith(expect.objectContaining({ time: 180, close: 120 }));

    ws.emit('market.candle', { symbol: 'BTCUSDT', timeframe: '1m', candle: bar(240, '121') });
    expect(ref.current.latestTime).toBe(240);
    ws.emit('market.stream', { symbol: 'BTCUSDT', timeframe: '1m', state: 'live' });
    await waitFor(() => {
      expect(result.current.stream).toBe('live');
    });
  });

  it('switching symbol resets the chart and ignores stale events and late history', async () => {
    const btc = deferred<CandleList>();
    const eth = deferred<CandleList>();
    vi.spyOn(marketsApi, 'candles').mockImplementation((symbol) =>
      symbol === 'BTCUSDT' ? btc.promise : eth.promise,
    );
    const { ref, series } = makeChart();
    const { result, rerender } = renderHook(
      ({ symbol }) => useMarketChart(ref, symbol, '5m', undefined),
      { initialProps: { symbol: 'BTCUSDT' } },
    );
    rerender({ symbol: 'ETHUSDT' });
    expect(ws.sent).toContainEqual({
      type: 'market.unsubscribe',
      data: { symbol: 'BTCUSDT', timeframe: '5m' },
    });
    expect(series.setData).toHaveBeenLastCalledWith([]); // cleared immediately

    await act(async () => {
      eth.resolve(history('ETHUSDT', '5m', [300, 600]));
      await eth.promise;
    });
    const setDataCalls = series.setData.mock.calls.length;
    // Late BTC history and BTC candles must not touch the ETH chart.
    await act(async () => {
      btc.resolve(history('BTCUSDT', '5m', [300, 600, 900]));
      await btc.promise;
    });
    ws.emit('market.candle', { symbol: 'BTCUSDT', timeframe: '5m', candle: bar(900, '1') });
    expect(series.setData.mock.calls.length).toBe(setDataCalls);
    expect(series.update).not.toHaveBeenCalled();
    expect(ref.current.latestTime).toBe(600);
    expect(result.current.load.status).toBe('ready');
  });

  it('switching timeframe (incl. 10m) resubscribes and reloads with the new timeframe', async () => {
    const spy = vi
      .spyOn(marketsApi, 'candles')
      .mockImplementation((symbol, timeframe) =>
        Promise.resolve(history(symbol, timeframe, [600, 1200])),
      );
    const { ref } = makeChart();
    const { result, rerender } = renderHook(
      ({ tf }: { tf: Timeframe }) => useMarketChart(ref, 'BTCUSDT', tf, undefined),
      { initialProps: { tf: '5m' as Timeframe } },
    );
    await waitFor(() => {
      expect(result.current.load.status).toBe('ready');
    });
    rerender({ tf: '10m' });
    expect(result.current.load.status).toBe('loading'); // immediate loading state
    await waitFor(() => {
      expect(result.current.load.status).toBe('ready');
    });
    expect(spy).toHaveBeenLastCalledWith(
      'BTCUSDT',
      '10m',
      expect.any(Number),
      expect.any(AbortSignal),
    );
    expect(ws.sent).toContainEqual({
      type: 'market.subscribe',
      data: { symbol: 'BTCUSDT', timeframe: '10m' },
    });
    ws.emit('market.candle', { symbol: 'BTCUSDT', timeframe: '5m', candle: bar(1800) });
    expect(ref.current.latestTime).toBe(1200); // old timeframe's events ignored
  });

  it('two charts fail and load independently', async () => {
    vi.spyOn(marketsApi, 'candles').mockImplementation((symbol, timeframe) =>
      symbol === 'BADUSDT'
        ? Promise.reject(new ApiError(503, 'market_data_unavailable'))
        : Promise.resolve(history(symbol, timeframe, [60])),
    );
    const a = makeChart();
    const b = makeChart();
    const one = renderHook(() => useMarketChart(a.ref, 'BTCUSDT', '1m', undefined));
    const two = renderHook(() => useMarketChart(b.ref, 'BADUSDT', '1m', undefined));
    await waitFor(() => {
      expect(two.result.current.load).toEqual({ status: 'error', code: 'history_failed' });
    });
    expect(one.result.current.load).toEqual({ status: 'ready', empty: false });
  });

  it('maps unavailable contracts and rate limiting', async () => {
    vi.spyOn(marketsApi, 'candles')
      .mockRejectedValueOnce(new ApiError(409, 'symbol_unavailable'))
      .mockRejectedValueOnce(new ApiError(503, 'market_data_rate_limited', 5));
    const { ref } = makeChart();
    const { result } = renderHook(() => useMarketChart(ref, 'OLDUSDT', '1m', undefined));
    await waitFor(() => {
      expect(result.current.load).toEqual({ status: 'unavailable' });
    });
    act(() => {
      result.current.reload();
    });
    await waitFor(() => {
      expect(result.current.load).toEqual({ status: 'error', code: 'rate_limited' });
    });
  });

  it('resync events reload history', async () => {
    const spy = vi
      .spyOn(marketsApi, 'candles')
      .mockImplementation((symbol, timeframe) => Promise.resolve(history(symbol, timeframe, [60])));
    const { ref } = makeChart();
    const { result } = renderHook(() => useMarketChart(ref, 'BTCUSDT', '1m', undefined));
    await waitFor(() => {
      expect(result.current.load.status).toBe('ready');
    });
    act(() => {
      ws.emit('market.resync', { symbol: 'BTCUSDT', timeframe: '1m', reason: 'reconnect' });
    });
    await waitFor(() => {
      expect(spy).toHaveBeenCalledTimes(2);
    });
  });
});
