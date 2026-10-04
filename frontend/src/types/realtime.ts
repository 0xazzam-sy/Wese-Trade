/** Stable envelope for every message on the internal WebSocket. */
export interface EventEnvelope<TData = Record<string, unknown>> {
  type: string;
  timestamp: string; // UTC ISO-8601
  data: TData;
}

export const EVENT_TYPES = {
  systemStatus: 'system.status',
  systemHeartbeat: 'system.heartbeat',
  systemPing: 'system.ping',
  systemPong: 'system.pong',
  systemError: 'system.error',
  // Reserved for later phases (never emitted by the phase 1 backend):
  marketTick: 'market.tick',
  marketCandle: 'market.candle',
  analysisUpdate: 'analysis.update',
  signalDeveloping: 'signal.developing',
  signalConfirmed: 'signal.confirmed',
  signalUpdated: 'signal.updated',
  signalClosed: 'signal.closed',
  scannerUpdate: 'scanner.update',
} as const;

export type ConnectionState = 'connecting' | 'connected' | 'disconnected';

/** Application close codes (must match backend `app.websocket.events`). */
export const WS_CLOSE_UNAUTHORIZED = 4401;
export const WS_CLOSE_SESSION_EXPIRED = 4403;
