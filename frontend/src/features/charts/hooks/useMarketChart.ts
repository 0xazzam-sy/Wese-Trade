import { useCallback, useEffect, useState } from 'react';

import { applyAnalysisUpdate } from '@/features/analysis/lib/merge';
import type { ChartController } from '@/features/charts/lib/ChartController';
import { priceFormatFor } from '@/features/charts/lib/candles';
import { ApiError } from '@/lib/http';
import { marketsApi } from '@/services/api/markets';
import { marketFeed } from '@/services/realtime/marketFeed';
import type { AnalysisSnapshot } from '@/types/analysis';
import type { SignalView } from '@/types/signal';
import type { CandleBar, MarketSymbol, StreamState, Timeframe } from '@/types/market';

export const HISTORY_LIMIT = 800;

export type ChartLoadState =
  | { status: 'loading' }
  | { status: 'ready'; empty: boolean }
  | { status: 'error'; code: 'history_failed' | 'rate_limited' | 'loading_metadata' }
  | { status: 'unavailable' };

export interface MarketChartState {
  load: ChartLoadState;
  stream: StreamState | null;
  /** Backend analysis for exactly this symbol/timeframe (null until the first update). */
  analysis: AnalysisSnapshot | null;
  /** Signals for exactly this symbol/timeframe (null until the first signal event). */
  signal: SignalView | null;
  reload: () => void;
}

function classify(error: unknown): ChartLoadState {
  if (error instanceof ApiError) {
    if (error.status === 404 || error.status === 409) return { status: 'unavailable' };
    if (error.code === 'market_data_rate_limited') return { status: 'error', code: 'rate_limited' };
    if (error.code === 'market_data_loading') return { status: 'error', code: 'loading_metadata' };
  }
  return { status: 'error', code: 'history_failed' };
}

/**
 * Drives one chart: reset -> subscribe (buffering) -> load history -> flush buffer -> live.
 *
 * Race safety: every (symbol, timeframe, reload) run gets its own `active` flag. Handlers
 * from a previous run are unsubscribed and also check the flag, so a late candle or a late
 * history response for the previous selection can never reach the chart.
 */
export function useMarketChart(
  controllerRef: React.RefObject<ChartController | null>,
  symbol: string,
  timeframe: Timeframe,
  meta: MarketSymbol | undefined,
): MarketChartState {
  const [reloadToken, setReloadToken] = useState(0);
  const reload = useCallback(() => {
    setReloadToken((n) => n + 1);
  }, []);
  // State is tagged with the run that produced it: a new symbol/timeframe/reload reads as
  // "loading" immediately, without a synchronous reset inside the effect.
  const runKey = `${symbol}|${timeframe}|${reloadToken}`;
  const [loadState, setLoadState] = useState<{ key: string; value: ChartLoadState } | null>(null);
  const [streamState, setStreamState] = useState<{ key: string; value: StreamState } | null>(null);
  // Analysis survives a history reload of the same stream, but never a symbol/timeframe switch.
  const streamKey = `${symbol}|${timeframe}`;
  const [analysisState, setAnalysisState] = useState<{
    key: string;
    value: AnalysisSnapshot | null;
  } | null>(null);
  const load: ChartLoadState = loadState?.key === runKey ? loadState.value : { status: 'loading' };
  const stream = streamState?.key === runKey ? streamState.value : null;
  const analysis = analysisState?.key === streamKey ? analysisState.value : null;
  const [signalState, setSignalState] = useState<{ key: string; value: SignalView } | null>(null);
  const signal = signalState?.key === streamKey ? signalState.value : null;

  useEffect(() => {
    // setData() does not reset series options, so this survives chart resets.
    controllerRef.current?.setPriceFormat(priceFormatFor(meta));
  }, [controllerRef, meta]);

  useEffect(() => {
    let active = true;
    const key = `${symbol}|${timeframe}|${reloadToken}`;
    const setLoad = (value: ChartLoadState) => {
      setLoadState({ key, value });
    };
    const setStream = (value: StreamState) => {
      setStreamState({ key, value });
    };
    // New chart context: clear candles, restore auto-scale, start a new generation.
    const generation = controllerRef.current?.reset() ?? 0;

    const buffer: CandleBar[] = [];
    let historyLoaded = false;
    const abort = new AbortController();

    const applyLive = (bar: CandleBar) => {
      const result = controllerRef.current?.applyBar(bar);
      if (result === 'gap') reload();
    };

    const unsubscribe = marketFeed.subscribe(symbol, timeframe, {
      onCandle: (bar) => {
        if (!active) return;
        if (historyLoaded) applyLive(bar);
        else buffer.push(bar);
      },
      onStream: (state) => {
        if (!active) return;
        setStream(state);
        if (state === 'unavailable') setLoad({ status: 'unavailable' });
      },
      onResync: () => {
        if (active) reload();
      },
      onSignal: (view) => {
        if (!active || view.symbol !== symbol || view.timeframe !== timeframe) return;
        setSignalState({ key: `${symbol}|${timeframe}`, value: view });
      },
      onAnalysis: (update) => {
        if (!active) return;
        const expected = { symbol, timeframe };
        const key = `${symbol}|${timeframe}`;
        setAnalysisState((prev) => ({
          key,
          value: applyAnalysisUpdate(prev?.key === key ? prev.value : null, update, expected),
        }));
      },
      onError: (code) => {
        if (!active) return;
        if (code === 'unknown_symbol' || code === 'symbol_unavailable') {
          setLoad({ status: 'unavailable' });
        }
      },
    });

    marketsApi
      .candles(symbol, timeframe, HISTORY_LIMIT, abort.signal)
      .then((response) => {
        if (!active) return;
        const chart = controllerRef.current;
        // Double guard against stale responses: the run flag AND the chart generation.
        if (response.symbol !== symbol || response.timeframe !== timeframe) return;
        const count = chart?.setHistory(response.candles, generation) ?? 0;
        if (count < 0) return;
        historyLoaded = true;
        const latest = chart?.latestTime ?? null;
        for (const bar of buffer.splice(0)) {
          if (latest === null || bar.time >= latest) applyLive(bar);
        }
        setLoad({ status: 'ready', empty: count === 0 });
      })
      .catch((error: unknown) => {
        if (!active || (error instanceof DOMException && error.name === 'AbortError')) return;
        setLoad(classify(error));
      });

    return () => {
      active = false;
      abort.abort();
      unsubscribe();
    };
  }, [controllerRef, symbol, timeframe, reloadToken, reload]);

  return { load, stream, analysis, signal, reload };
}
