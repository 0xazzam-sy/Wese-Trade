import type { CandleBar, MarketFeedState, StreamState, Timeframe } from '@/types/market';
import type { EventEnvelope } from '@/types/realtime';

import type { RealtimeClient } from './RealtimeClient';

export interface StreamHandlers {
  onCandle: (bar: CandleBar) => void;
  onStream?: (state: StreamState) => void;
  /** History may have changed (exchange gap recovery or our own reconnect): refetch it. */
  onResync?: () => void;
  onError?: (code: string) => void;
}

type TickHandler = (price: string, timestamp: string) => void;
type StatusHandler = (state: MarketFeedState) => void;

const keyOf = (symbol: string, timeframe: Timeframe) => `${symbol}|${timeframe}`;

/**
 * Market subscriptions over the single app WebSocket.
 *
 * - Reference-counted: two charts on the same symbol/timeframe share one server subscription.
 * - Events are routed by (symbol, timeframe) key, so a chart never receives another
 *   stream's candles — including late events from a stream it just switched away from.
 * - Survives app-WebSocket reconnects: resubscribes and asks consumers to resync history.
 * - Exists before the socket does (charts mount before the connection is opened).
 */
export class MarketFeed {
  private client: RealtimeClient | null = null;
  private readonly unsubscribers: (() => void)[] = [];
  private readonly streams = new Map<
    string,
    { symbol: string; timeframe: Timeframe; handlers: Set<StreamHandlers> }
  >();
  private readonly ticks = new Map<string, Set<TickHandler>>();
  private readonly statusHandlers = new Set<StatusHandler>();
  private connectedOnce = false;

  attach(client: RealtimeClient): void {
    this.detach();
    this.client = client;
    this.connectedOnce = false;
    this.unsubscribers.push(
      client.subscribe('system.status', (e) => {
        if (e.data.state === 'connected') this.onConnected();
      }),
      client.subscribe('market.candle', (e) => {
        this.dispatch(e, (h, data) => {
          h.onCandle(data.candle as CandleBar);
        });
      }),
      client.subscribe('market.stream', (e) => {
        this.dispatch(e, (h, data) => h.onStream?.(data.state as StreamState));
      }),
      client.subscribe('market.resync', (e) => {
        this.dispatch(e, (h) => h.onResync?.());
      }),
      client.subscribe('system.error', (e) => {
        if (typeof e.data.symbol === 'string' && typeof e.data.timeframe === 'string') {
          const code = String(e.data.code);
          // The error refers to the raw request; match case-insensitively.
          const symbol = e.data.symbol.toUpperCase();
          this.dispatchKey(keyOf(symbol, e.data.timeframe as Timeframe), (h) => h.onError?.(code));
        }
      }),
      client.subscribe('market.tick', (e) => {
        const symbol = String(e.data.symbol);
        this.ticks.get(symbol)?.forEach((handler) => {
          handler(String(e.data.price), String(e.data.timestamp));
        });
      }),
      client.subscribe('market.status', (e) => {
        this.statusHandlers.forEach((handler) => {
          handler(e.data.state as MarketFeedState);
        });
      }),
    );
  }

  detach(): void {
    this.unsubscribers.splice(0).forEach((unsubscribe) => {
      unsubscribe();
    });
    this.client = null;
  }

  subscribe(symbol: string, timeframe: Timeframe, handlers: StreamHandlers): () => void {
    const key = keyOf(symbol, timeframe);
    let entry = this.streams.get(key);
    if (!entry) {
      entry = { symbol, timeframe, handlers: new Set() };
      this.streams.set(key, entry);
      this.client?.send('market.subscribe', { symbol, timeframe });
    }
    entry.handlers.add(handlers);
    return () => {
      const current = this.streams.get(key);
      if (!current) return;
      current.handlers.delete(handlers);
      if (current.handlers.size === 0) {
        this.streams.delete(key);
        this.client?.send('market.unsubscribe', { symbol, timeframe });
      }
    };
  }

  onTick(symbol: string, handler: TickHandler): () => void {
    let set = this.ticks.get(symbol);
    if (!set) {
      set = new Set();
      this.ticks.set(symbol, set);
    }
    set.add(handler);
    return () => {
      set.delete(handler);
      if (set.size === 0) this.ticks.delete(symbol);
    };
  }

  onStatus(handler: StatusHandler): () => void {
    this.statusHandlers.add(handler);
    return () => this.statusHandlers.delete(handler);
  }

  private onConnected(): void {
    for (const entry of this.streams.values()) {
      this.client?.send('market.subscribe', { symbol: entry.symbol, timeframe: entry.timeframe });
    }
    // After an app-socket reconnect, events may have been missed: consumers refetch history.
    if (this.connectedOnce) {
      for (const entry of this.streams.values()) entry.handlers.forEach((h) => h.onResync?.());
    }
    this.connectedOnce = true;
  }

  private dispatch(
    e: EventEnvelope,
    fn: (handlers: StreamHandlers, data: Record<string, unknown>) => void,
  ): void {
    const { symbol, timeframe } = e.data;
    if (typeof symbol !== 'string' || typeof timeframe !== 'string') return;
    this.dispatchKey(keyOf(symbol, timeframe as Timeframe), (h) => {
      fn(h, e.data);
    });
  }

  private dispatchKey(key: string, fn: (handlers: StreamHandlers) => void): void {
    this.streams.get(key)?.handlers.forEach(fn);
  }
}

/** App-wide singleton; the realtime hook attaches the live socket to it. */
export const marketFeed = new MarketFeed();
