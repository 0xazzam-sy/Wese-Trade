import { useQuery } from '@tanstack/react-query';
import { useMemo } from 'react';

import { marketsApi } from '@/services/api/markets';
import type { MarketSymbol, Ticker } from '@/types/market';

const SYMBOLS_KEY = ['markets', 'symbols'] as const;
const TICKERS_KEY = ['markets', 'tickers'] as const;

/** All active USDT perpetuals (one request, shared by every consumer). */
export function useSymbols() {
  return useQuery({
    queryKey: SYMBOLS_KEY,
    queryFn: ({ signal }) => marketsApi.symbols(signal),
    staleTime: 10 * 60_000,
    refetchInterval: 15 * 60_000,
    retry: (count) => count < 20, // backend may still be loading metadata from the exchange
    retryDelay: (attempt) => Math.min(30_000, 1000 * 2 ** attempt),
  });
}

export function useSymbolMap(): Map<string, MarketSymbol> {
  const { data } = useSymbols();
  return useMemo(() => new Map((data?.items ?? []).map((s) => [s.symbol, s])), [data]);
}

/** 24h statistics for every symbol in one bulk request, refreshed every 10s. */
export function useTickers() {
  return useQuery({
    queryKey: TICKERS_KEY,
    queryFn: ({ signal }) => marketsApi.tickers(signal),
    refetchInterval: 10_000,
    staleTime: 5_000,
  });
}

export function useTickerMap(): Map<string, Ticker> {
  const { data } = useTickers();
  return useMemo(() => new Map((data?.items ?? []).map((t) => [t.symbol, t])), [data]);
}
