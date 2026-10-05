import { apiRequest } from '@/lib/http';
import type { HealthResponse, RuntimeInfo } from '@/types/system';

export const systemApi = {
  health(signal?: AbortSignal): Promise<HealthResponse> {
    return apiRequest<HealthResponse>('/health', signal ? { signal } : {});
  },

  runtime(signal?: AbortSignal): Promise<RuntimeInfo> {
    return apiRequest<RuntimeInfo>('/system/runtime', signal ? { signal } : {});
  },
};
