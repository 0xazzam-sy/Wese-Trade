import { useQuery } from '@tanstack/react-query';
import { useMemo } from 'react';

import { forwardTestApi } from '@/services/api/forwardTest';
import type { SignalDTO, SignalView } from '@/types/signal';

import { isSignalTimeframe, mergeChartSignals } from './chartSignals';

const NONE: readonly SignalDTO[] = [];

/**
 * Confirmed forward-test signals of one chart stream: persisted history (REST, so markers
 * come back after a restart) merged with the live WebSocket view, de-duplicated by id.
 * Research-only timeframes (1m/5m/10m) never fetch and never return anything.
 */
export function useChartSignals(
  symbol: string,
  timeframe: string,
  view: SignalView | null,
): SignalDTO[] {
  const enabled = isSignalTimeframe(timeframe);
  const { data } = useQuery({
    queryKey: ['forward-test', 'chart-signals', symbol, timeframe],
    queryFn: ({ signal }) => forwardTestApi.chartSignals(symbol, timeframe, signal),
    enabled,
    staleTime: 60_000,
    refetchInterval: 5 * 60_000,
  });
  const history =
    enabled && data?.symbol === symbol && data.timeframe === timeframe ? data.items : NONE;
  return useMemo(
    () => mergeChartSignals(history, view, symbol, timeframe),
    [history, view, symbol, timeframe],
  );
}
