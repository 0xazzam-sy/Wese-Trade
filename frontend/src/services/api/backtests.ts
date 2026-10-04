import { apiRequest } from '@/lib/http';
import type { BacktestRun, BacktestRunSummary } from '@/types/backtest';

const withSignal = (signal?: AbortSignal) => (signal ? { signal } : {});

export const backtestsApi = {
  list(signal?: AbortSignal): Promise<{ items: BacktestRunSummary[] }> {
    return apiRequest<{ items: BacktestRunSummary[] }>('/backtests', withSignal(signal));
  },

  get(id: number, signal?: AbortSignal): Promise<BacktestRun> {
    return apiRequest<BacktestRun>(`/backtests/${String(id)}`, withSignal(signal));
  },
};
