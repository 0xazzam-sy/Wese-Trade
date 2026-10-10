export interface HealthResponse {
  status: 'ok' | 'degraded';
  service: string;
  version: string;
  api_version: string;
  database: { status: 'ok' | 'unavailable' };
  timestamp: string;
}

/** GET /system/runtime: what this installation is running (no secrets). */
export interface RuntimeInfo {
  app_version: string;
  mode: 'development' | 'desktop';
  market_provider: string;
  strategy: {
    name: string;
    version: string | null;
    fingerprint: string | null;
    status: string | null;
  };
  /** The frozen Strategy 4.2 forward test kept as the baseline (v1.2). */
  baseline?: {
    name: string;
    version: string | null;
    fingerprint: string | null;
    status: string | null;
  };
  news_enabled: boolean;
  weather_enabled: boolean;
  paths?: { root: string; data: string; logs: string; exports: string; backups: string };
}
