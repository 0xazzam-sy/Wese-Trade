import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { ConnectionState } from '@/types/realtime';

import { RealtimeClient } from './RealtimeClient';

class FakeSocket {
  static instances: FakeSocket[] = [];
  readyState: number = WebSocket.CONNECTING;
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: unknown }) => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(readonly url: string) {
    FakeSocket.instances.push(this);
  }
  send(data: string) {
    this.sent.push(data);
  }
  close(code = 1000) {
    this.readyState = WebSocket.CLOSED;
    this.onclose?.({ code });
  }
  // Test helpers
  serverOpen() {
    this.readyState = WebSocket.OPEN;
    this.onopen?.();
  }
  serverSend(payload: object) {
    this.onmessage?.({ data: JSON.stringify(payload) });
  }
  serverClose(code: number) {
    this.readyState = WebSocket.CLOSED;
    this.onclose?.({ code });
  }
}

function socketAt(index: number): FakeSocket {
  const socket = FakeSocket.instances[index];
  if (!socket) throw new Error(`no socket #${index}`);
  return socket;
}

function makeClient(states: ConnectionState[], onUnauthorized = vi.fn()) {
  return new RealtimeClient({
    url: 'ws://test/api/v1/ws',
    onStateChange: (s) => states.push(s),
    onUnauthorized,
    backoffBaseMs: 100,
    random: () => 0.5, // no jitter
    webSocketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
  });
}

const connectedEnvelope = {
  type: 'system.status',
  timestamp: '2026-01-01T00:00:00Z',
  data: { state: 'connected' },
};

describe('RealtimeClient', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    FakeSocket.instances = [];
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('goes connecting → connected after the server status event', () => {
    const states: ConnectionState[] = [];
    const client = makeClient(states);
    client.connect();
    const socket = socketAt(0);
    socket.serverOpen();
    expect(client.connectionState).toBe('connecting');
    socket.serverSend(connectedEnvelope);
    expect(states).toEqual(['connecting', 'connected']);
  });

  it('dispatches events to subscribers', () => {
    const client = makeClient([]);
    const handler = vi.fn();
    client.subscribe('system.heartbeat', handler);
    client.connect();
    socketAt(0).serverOpen();
    socketAt(0).serverSend({ type: 'system.heartbeat', timestamp: 't', data: {} });
    expect(handler).toHaveBeenCalledOnce();
  });

  it('reconnects with exponential backoff after an unexpected close', () => {
    const states: ConnectionState[] = [];
    const client = makeClient(states);
    client.connect();
    socketAt(0).serverClose(1006);
    expect(client.connectionState).toBe('connecting');

    vi.advanceTimersByTime(99);
    expect(FakeSocket.instances).toHaveLength(1);
    vi.advanceTimersByTime(1);
    expect(FakeSocket.instances).toHaveLength(2);

    socketAt(1).serverClose(1006);
    vi.advanceTimersByTime(199);
    expect(FakeSocket.instances).toHaveLength(2);
    vi.advanceTimersByTime(1);
    expect(FakeSocket.instances).toHaveLength(3);
  });

  it('reports disconnected after repeated failures while still retrying', () => {
    const states: ConnectionState[] = [];
    const client = makeClient(states);
    client.connect();
    socketAt(0).serverClose(1006);
    expect(client.connectionState).toBe('connecting');
    vi.advanceTimersByTime(100);
    socketAt(1).serverClose(1006);
    expect(client.connectionState).toBe('disconnected');
    vi.advanceTimersByTime(200);
    expect(FakeSocket.instances).toHaveLength(3);
    expect(client.connectionState).toBe('disconnected');

    socketAt(2).serverOpen();
    socketAt(2).serverSend(connectedEnvelope);
    expect(client.connectionState).toBe('connected');
    expect(states).toEqual(['connecting', 'disconnected', 'connected']);
  });

  it('stops and reports when the server rejects the session', () => {
    const onUnauthorized = vi.fn();
    const client = makeClient([], onUnauthorized);
    client.connect();
    socketAt(0).serverOpen();
    socketAt(0).serverClose(4401);
    expect(client.connectionState).toBe('disconnected');
    expect(onUnauthorized).toHaveBeenCalledOnce();
    vi.advanceTimersByTime(60_000);
    expect(FakeSocket.instances).toHaveLength(1);
  });

  it('sends pings and does not reconnect after disconnect()', () => {
    const client = makeClient([]);
    client.connect();
    const socket = socketAt(0);
    socket.serverOpen();
    vi.advanceTimersByTime(15_000);
    expect(socket.sent.map((m) => JSON.parse(m) as { type: string })).toEqual([
      { type: 'system.ping', data: {} },
    ]);

    client.disconnect();
    expect(client.connectionState).toBe('disconnected');
    vi.advanceTimersByTime(60_000);
    expect(FakeSocket.instances).toHaveLength(1);
  });
});
