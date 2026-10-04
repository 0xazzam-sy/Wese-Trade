import type { RealtimeClient } from '@/services/realtime/RealtimeClient';
import type { EventEnvelope } from '@/types/realtime';

type Handler = (e: EventEnvelope) => void;

/** Minimal stand-in for RealtimeClient: records sends, lets tests emit server events. */
export class FakeRealtime {
  sent: { type: string; data: Record<string, unknown> }[] = [];
  private handlers = new Map<string, Set<Handler>>();

  subscribe(type: string, handler: Handler): () => void {
    let set = this.handlers.get(type);
    if (!set) {
      set = new Set();
      this.handlers.set(type, set);
    }
    set.add(handler);
    return () => set.delete(handler);
  }

  send(type: string, data: Record<string, unknown> = {}): boolean {
    this.sent.push({ type, data });
    return true;
  }

  emit(type: string, data: Record<string, unknown>): void {
    const envelope: EventEnvelope = { type, timestamp: '2026-10-03T12:00:00Z', data };
    this.handlers.get(type)?.forEach((h) => {
      h(envelope);
    });
  }

  connected(): void {
    this.emit('system.status', { state: 'connected' });
  }

  asClient(): RealtimeClient {
    return this as unknown as RealtimeClient;
  }
}

export function bar(time: number, close = '100', isClosed = false) {
  return { time, open: '100', high: '110', low: '90', close, volume: '1', is_closed: isClosed };
}
