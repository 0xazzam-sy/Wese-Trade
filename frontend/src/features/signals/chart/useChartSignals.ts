import { useQuery } from '@tanstack/react-query';
import { useMemo } from 'react';

import { strategy43Api } from '@/services/api/strategy43';
import type { SignalDTO, SignalView } from '@/types/signal';

import { isSignalTimeframe, mergeChartSignals } from './chartSignals';

const NONE: readonly SignalDTO[] = [];

/**
 * Confirmed Strategy 4.3 signals of one chart stream: persisted history (REST, so markers
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
    queryKey: ['strategy43', 'chart-signals', symbol, timeframe],
    queryFn: ({ signal }) => strategy43Api.chartSignals(symbol, timeframe, signal),
    enabled,
    staleTime: 60_000,
    refetchInterval: 60_000,
  });
  const history =
    enabled && data?.symbol === symbol && data.timeframe === timeframe ? data.items : NONE;
  return useMemo(
    () => mergeChartSignals(history, view, symbol, timeframe),
    [history, view, symbol, timeframe],
  );
}
