import { apiRequest } from '@/lib/http';
import type { SignalDTO } from '@/types/signal';
import type { EngineHealth, OpportunitiesResponse } from '@/types/strategy43';

export interface ChartSignalsResponse {
  symbol: string;
  timeframe: string;
  signal_capable: boolean;
  strategy_version?: string;
  fingerprint?: string;
  items: SignalDTO[];
}

const withSignal = (signal?: AbortSignal) => (signal ? { signal } : {});

/** Read-only Strategy 4.3 API: engine health, market scanner, chart signal history. */
export const strategy43Api = {
  health(signal?: AbortSignal): Promise<EngineHealth> {
    return apiRequest<EngineHealth>('/strategy43/health', withSignal(signal));
  },

  opportunities(limit = 20, signal?: AbortSignal): Promise<OpportunitiesResponse> {
    return apiRequest(`/strategy43/opportunities?limit=${String(limit)}`, withSignal(signal));
  },

  chartSignals(
    symbol: string,
    timeframe: string,
    signal?: AbortSignal,
  ): Promise<ChartSignalsResponse> {
    const query = new URLSearchParams({ symbol, timeframe });
    return apiRequest(`/strategy43/chart-signals?${query.toString()}`, withSignal(signal));
  },
};
