import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useMarketChart } from '@/features/charts/hooks/useMarketChart';
import { ChartController } from '@/features/charts/lib/ChartController';
import { strategy43Api } from '@/services/api/strategy43';
import { marketsApi } from '@/services/api/markets';
import { marketFeed } from '@/services/realtime/marketFeed';
import { FakeRealtime } from '@/test/fakeRealtime';
import { BUY, BUY_CANDLES, SELL } from '@/test/frozenSignals';
import { FORWARD_STRATEGY } from '@/test/signalFixture';
import type { Timeframe } from '@/types/market';

import { buildMarkerSpecs } from './chartSignals';
import { useChartSignals } from './useChartSignals';

const CANDLES = BUY_CANDLES;

let ws: FakeRealtime;
let client: QueryClient;
const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={client}>{children}</QueryClientProvider>
);

function chart(symbol: string, timeframe: Timeframe) {
  const series = { setData: vi.fn(), update: vi.fn(), applyOptions: vi.fn() };
  const ref = { current: new ChartController(series) };
  return renderHook(
    () => {
      const state = useMarketChart(ref, symbol, timeframe, undefined);
      const signals = useChartSignals(symbol, timeframe, state.signal);
      const markers = buildMarkerSpecs(signals, state.load.status === 'ready', (t) =>
        ref.current.hasTime(t),
      );
      return { state, signals, markers };
    },
    { wrapper },
  );
}

beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  ws = new FakeRealtime();
  marketFeed.attach(ws.asClient());
  vi.spyOn(marketsApi, 'candles').mockImplementation((symbol, timeframe) =>
    Promise.resolve({ symbol, timeframe, candles: CANDLES }),
  );
});

afterEach(() => {
  marketFeed.detach();
  vi.restoreAllMocks();
});

const base = { symbol: 'ETHUSDT', timeframe: '15m', strategy: FORWARD_STRATEGY };

describe('chart signals: persistence + WebSocket', () => {
  it('restores persisted markers after a restart (REST), without regenerating them', async () => {
    const api = vi.spyOn(strategy43Api, 'chartSignals').mockResolvedValue({
      symbol: 'ETHUSDT',
      timeframe: '15m',
      signal_capable: true,
      items: [BUY],
    });
    const { result } = chart('ETHUSDT', '15m');
    await waitFor(() => {
      expect(result.current.markers).toHaveLength(1);
    });
    expect(api).toHaveBeenCalledWith('ETHUSDT', '15m', expect.anything());
    expect(result.current.markers[0]).toMatchObject({ id: BUY.id, text: 'BUY · شراء' });
  });

  it('a new confirmed signal arrives live: marker without refresh, never duplicated', async () => {
    vi.spyOn(strategy43Api, 'chartSignals').mockResolvedValue({
      symbol: 'ETHUSDT',
      timeframe: '15m',
      signal_capable: true,
      items: [],
    });
    const { result } = chart('ETHUSDT', '15m');
    await waitFor(() => {
      expect(result.current.state.load.status).toBe('ready');
    });
    expect(result.current.markers).toEqual([]);

    act(() => {
      ws.emit('signal.confirmed', { ...base, signal: BUY });
    });
    expect(result.current.markers.map((m) => m.id)).toEqual([BUY.id]);

    // WebSocket reconnect: the server re-sends the full stream state on subscribe.
    act(() => {
      ws.emit('signal.updated', { ...base, active: BUY, last_confirmed: BUY, evaluation: null });
      ws.emit('signal.confirmed', { ...base, signal: BUY });
    });
    expect(result.current.markers.map((m) => m.id)).toEqual([BUY.id]);

    // the signal closes: the marker stays (history), no longer active
    act(() => {
      ws.emit('signal.closed', {
        ...base,
        signal: { ...BUY, state: 'stopped', state_time: BUY.state_time + 900 },
      });
    });
    expect(result.current.markers).toHaveLength(1);
    expect(result.current.markers[0]?.active).toBe(false);
  });

  it('history + live copy of the same signal = one marker', async () => {
    vi.spyOn(strategy43Api, 'chartSignals').mockResolvedValue({
      symbol: 'ETHUSDT',
      timeframe: '15m',
      signal_capable: true,
      items: [BUY],
    });
    const { result } = chart('ETHUSDT', '15m');
    await waitFor(() => {
      expect(result.current.markers).toHaveLength(1);
    });
    act(() => {
      ws.emit('signal.confirmed', { ...base, signal: BUY });
    });
    expect(result.current.markers).toHaveLength(1);
  });

  it('two charts are independent: no cross-chart marker leakage', async () => {
    vi.spyOn(strategy43Api, 'chartSignals').mockImplementation((symbol, timeframe) =>
      Promise.resolve({
        symbol,
        timeframe,
        signal_capable: true,
        items: symbol === 'ETHUSDT' && timeframe === '15m' ? [BUY] : [],
      }),
    );
    const eth = chart('ETHUSDT', '15m');
    const btc = chart('BTCUSDT', '1h');
    await waitFor(() => {
      expect(eth.result.current.markers).toHaveLength(1);
    });
    act(() => {
      ws.emit('signal.confirmed', { ...base, signal: SELL });
    });
    expect(btc.result.current.signals).toEqual([]);
    expect(btc.result.current.markers).toEqual([]);
    expect(eth.result.current.signals.map((s) => s.id).sort()).toEqual([BUY.id, SELL.id].sort());
  });

  it('research-only timeframe: no request, no markers, even if an event arrives', async () => {
    const api = vi.spyOn(strategy43Api, 'chartSignals');
    const { result } = chart('ETHUSDT', '5m');
    await waitFor(() => {
      expect(result.current.state.load.status).toBe('ready');
    });
    act(() => {
      ws.emit('signal.confirmed', {
        ...base,
        timeframe: '5m',
        signal: { ...BUY, timeframe: '5m' },
      });
    });
    expect(api).not.toHaveBeenCalled();
    expect(result.current.markers).toEqual([]);
  });
});
