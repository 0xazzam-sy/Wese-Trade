import { apiRequest } from '@/lib/http';
import type { HealthResponse } from '@/types/system';

export const systemApi = {
  health(signal?: AbortSignal): Promise<HealthResponse> {
    return apiRequest<HealthResponse>('/health', signal ? { signal } : {});
  },
};
