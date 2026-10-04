import { apiRequest } from '@/lib/http';
import type {
  CandleList,
  MarketHealth,
  SymbolDetails,
  SymbolList,
  TickerList,
  Timeframe,
} from '@/types/market';

const withSignal = (signal?: AbortSignal) => (signal ? { signal } : {});

export const marketsApi = {
  symbols(signal?: AbortSignal): Promise<SymbolList> {
    return apiRequest<SymbolList>('/markets/symbols', withSignal(signal));
  },

  tickers(signal?: AbortSignal): Promise<TickerList> {
    return apiRequest<TickerList>('/markets/tickers', withSignal(signal));
  },

  candles(
    symbol: string,
    timeframe: Timeframe,
    limit: number,
    signal?: AbortSignal,
  ): Promise<CandleList> {
    const query = new URLSearchParams({ timeframe, limit: String(limit) });
    return apiRequest<CandleList>(
      `/markets/${encodeURIComponent(symbol)}/candles?${query.toString()}`,
      withSignal(signal),
    );
  },

  details(symbol: string, signal?: AbortSignal): Promise<SymbolDetails> {
    return apiRequest<SymbolDetails>(
      `/markets/${encodeURIComponent(symbol)}/details`,
      withSignal(signal),
    );
  },

  health(signal?: AbortSignal): Promise<MarketHealth> {
    return apiRequest<MarketHealth>('/markets/health', withSignal(signal));
  },
};
