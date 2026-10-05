import { apiBaseUrl } from '@/lib/env';
import { apiRequest } from '@/lib/http';
import type {
  ForwardRun,
  ForwardSignalFilters,
  ForwardSignalRow,
  ForwardStatusCard,
} from '@/types/forwardTest';

const withSignal = (signal?: AbortSignal) => (signal ? { signal } : {});

/** Read-only forward-test API; the only writes are admin pause / resume / stop. */
export const forwardTestApi = {
  status(signal?: AbortSignal): Promise<ForwardStatusCard> {
    return apiRequest<ForwardStatusCard>('/forward-test/status', withSignal(signal));
  },

  runs(signal?: AbortSignal): Promise<{ items: { id: number; status: string }[] }> {
    return apiRequest('/forward-test/runs', withSignal(signal));
  },

  run(id: number, signal?: AbortSignal): Promise<ForwardRun> {
    return apiRequest<ForwardRun>(`/forward-test/runs/${String(id)}`, withSignal(signal));
  },

  signals(
    id: number,
    filters: ForwardSignalFilters,
    signal?: AbortSignal,
  ): Promise<{ items: ForwardSignalRow[] }> {
    const query = new URLSearchParams();
    for (const [k, v] of Object.entries(filters) as [string, string | undefined][])
      if (v) query.set(k, v);
    return apiRequest(
      `/forward-test/runs/${String(id)}/signals?${query.toString()}`,
      withSignal(signal),
    );
  },

  control(id: number, action: 'pause' | 'resume' | 'stop', note: string): Promise<unknown> {
    return apiRequest(`/forward-test/runs/${String(id)}/${action}`, {
      method: 'POST',
      body: { note },
    });
  },

  exportUrl(id: number, format: 'json' | 'csv'): string {
    return `${apiBaseUrl}/forward-test/runs/${String(id)}/export?format=${format}`;
  },
};
