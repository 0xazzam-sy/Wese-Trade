export interface HealthResponse {
  status: 'ok' | 'degraded';
  service: string;
  version: string;
  api_version: string;
  database: { status: 'ok' | 'unavailable' };
  timestamp: string;
}

/** Honest status for backend modules that are not implemented yet. */
export interface ModuleStatus {
  module: string;
  available: boolean;
  phase: string;
  message: string;
}
