import type { ChartCandle } from '@/features/charts/lib/candles';
import type { SymbolCode, SymbolMeta, Timeframe } from '@/types/market';

export type FeedStatus = 'unavailable' | 'loading' | 'live' | 'error';

export interface ChartData {
  candles: readonly ChartCandle[];
  meta: SymbolMeta | null;
  feed: FeedStatus;
}

const EMPTY: ChartData = { candles: [], meta: null, feed: 'unavailable' };

/**
 * Market data source for a chart. Phase 1: the backend market data provider does not exist
 * yet, so this honestly reports `unavailable` with no candles (never fabricated data).
 * Phase 2 will back this with REST history + `market.candle` WebSocket events.
 */
export function useChartData(_symbol: SymbolCode, _timeframe: Timeframe): ChartData {
  return EMPTY;
}
