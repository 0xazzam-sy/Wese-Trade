import {
  type ConnectionState,
  EVENT_TYPES,
  type EventEnvelope,
  WS_CLOSE_SESSION_EXPIRED,
  WS_CLOSE_UNAUTHORIZED,
} from '@/types/realtime';

type EventHandler = (event: EventEnvelope) => void;

export interface RealtimeClientOptions {
  url: string;
  onStateChange?: (state: ConnectionState) => void;
  /** Called when the server rejects the session (close code 4401/4403). No reconnect follows. */
  onUnauthorized?: () => void;
  pingIntervalMs?: number;
  /** Force a reconnect if nothing is received for this long (server heartbeats every ~20s). */
  staleAfterMs?: number;
  backoffBaseMs?: number;
  backoffMaxMs?: number;
  /** Injectable for tests. */
  webSocketFactory?: (url: string) => WebSocket;
  random?: () => number;
}

const NORMAL_CLOSURE = 1000;
/** After this many consecutive failed attempts the state reads `disconnected` (still retrying). */
const FAILURES_BEFORE_DISCONNECTED = 2;

/**
 * Framework-agnostic WebSocket client with heartbeat, stale detection and
 * exponential-backoff reconnects. Holds no UI state; consumers subscribe to events.
 */
export class RealtimeClient {
  private socket: WebSocket | null = null;
  private state: ConnectionState = 'disconnected';
  private attempts = 0;
  private stopped = true;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private pingTimer: ReturnType<typeof setInterval> | null = null;
  private lastMessageAt = 0;
  private readonly handlers = new Map<string, Set<EventHandler>>();
  private readonly opts: Required<Omit<RealtimeClientOptions, 'onStateChange' | 'onUnauthorized'>> &
    Pick<RealtimeClientOptions, 'onStateChange' | 'onUnauthorized'>;

  constructor(options: RealtimeClientOptions) {
    this.opts = {
      pingIntervalMs: 15_000,
      staleAfterMs: 45_000,
      backoffBaseMs: 1_000,
      backoffMaxMs: 30_000,
      webSocketFactory: (url) => new WebSocket(url),
      random: Math.random,
      ...options,
    };
  }

  get connectionState(): ConnectionState {
    return this.state;
  }

  connect(): void {
    this.stopped = false;
    if (this.socket) return;
    this.open();
  }

  /** Close the connection and stop reconnecting. */
  disconnect(): void {
    this.stopped = true;
    this.clearTimers();
    this.closeSocket();
    this.setState('disconnected');
  }

  /** Drop the current socket (if any) and connect again immediately. */
  reconnectNow(): void {
    this.stopped = false;
    this.attempts = 0;
    this.clearTimers();
    this.closeSocket();
    this.open();
  }

  subscribe(type: string, handler: EventHandler): () => void {
    let set = this.handlers.get(type);
    if (!set) {
      set = new Set();
      this.handlers.set(type, set);
    }
    set.add(handler);
    return () => set.delete(handler);
  }

  send(type: string, data: Record<string, unknown> = {}): boolean {
    if (this.socket?.readyState !== WebSocket.OPEN) return false;
    this.socket.send(JSON.stringify({ type, data }));
    return true;
  }

  private get failing(): boolean {
    return this.attempts >= FAILURES_BEFORE_DISCONNECTED;
  }

  private open(): void {
    // While repeatedly failing, keep showing `disconnected` instead of flickering.
    if (!this.failing) this.setState('connecting');
    let socket: WebSocket;
    try {
      socket = this.opts.webSocketFactory(this.opts.url);
    } catch {
      this.scheduleReconnect();
      return;
    }
    this.socket = socket;

    socket.onopen = () => {
      this.attempts = 0;
      this.lastMessageAt = Date.now();
      this.startHeartbeat();
      // `connected` is set when the server's system.status arrives (auth succeeded).
    };
    socket.onmessage = (message: MessageEvent) => {
      this.lastMessageAt = Date.now();
      this.handleMessage(message.data);
    };
    socket.onclose = (event: CloseEvent) => {
      if (this.socket !== socket) return;
      this.socket = null;
      this.stopHeartbeat();
      if (event.code === WS_CLOSE_UNAUTHORIZED || event.code === WS_CLOSE_SESSION_EXPIRED) {
        this.stopped = true;
        this.setState('disconnected');
        this.opts.onUnauthorized?.();
        return;
      }
      this.scheduleReconnect();
    };
    socket.onerror = () => {
      // Errors are always followed by `close`; reconnect logic lives there.
    };
  }

  private handleMessage(raw: unknown): void {
    if (typeof raw !== 'string') return;
    let envelope: EventEnvelope;
    try {
      envelope = JSON.parse(raw) as EventEnvelope;
    } catch {
      return;
    }
    if (typeof envelope.type !== 'string') return;

    if (envelope.type === EVENT_TYPES.systemStatus && envelope.data.state === 'connected') {
      this.setState('connected');
    }
    this.handlers.get(envelope.type)?.forEach((handler) => {
      handler(envelope);
    });
    this.handlers.get('*')?.forEach((handler) => {
      handler(envelope);
    });
  }

  private scheduleReconnect(): void {
    if (this.stopped) {
      this.setState('disconnected');
      return;
    }
    this.setState(
      this.attempts + 1 >= FAILURES_BEFORE_DISCONNECTED ? 'disconnected' : 'connecting',
    );
    const exp = Math.min(this.opts.backoffMaxMs, this.opts.backoffBaseMs * 2 ** this.attempts);
    const jitter = exp * 0.2 * (this.opts.random() * 2 - 1);
    this.attempts += 1;
    this.reconnectTimer = setTimeout(
      () => {
        this.reconnectTimer = null;
        if (!this.stopped) this.open();
      },
      Math.max(0, Math.round(exp + jitter)),
    );
  }

  private startHeartbeat(): void {
    this.stopHeartbeat();
    this.pingTimer = setInterval(() => {
      if (Date.now() - this.lastMessageAt > this.opts.staleAfterMs) {
        // Connection silently died: force close; onclose schedules the reconnect.
        this.socket?.close(4000, 'stale');
        return;
      }
      this.send(EVENT_TYPES.systemPing);
    }, this.opts.pingIntervalMs);
  }

  private stopHeartbeat(): void {
    if (this.pingTimer !== null) clearInterval(this.pingTimer);
    this.pingTimer = null;
  }

  private clearTimers(): void {
    this.stopHeartbeat();
    if (this.reconnectTimer !== null) clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
  }

  private closeSocket(): void {
    const socket = this.socket;
    if (!socket) return;
    this.socket = null;
    socket.onmessage = null;
    socket.onclose = null;
    socket.onerror = null;
    if (socket.readyState === WebSocket.CONNECTING) {
      // Closing a CONNECTING socket logs a browser warning; close as soon as it opens.
      socket.onopen = () => {
        socket.close(NORMAL_CLOSURE);
      };
    } else {
      socket.onopen = null;
      socket.close(NORMAL_CLOSURE);
    }
  }

  private setState(next: ConnectionState): void {
    if (this.state === next) return;
    this.state = next;
    this.opts.onStateChange?.(next);
  }
}
