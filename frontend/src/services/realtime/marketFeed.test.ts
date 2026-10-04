import { describe, expect, it, vi } from 'vitest';

import { bar, FakeRealtime } from '@/test/fakeRealtime';

import { MarketFeed } from './marketFeed';

function setup() {
  const feed = new MarketFeed();
  const ws = new FakeRealtime();
  feed.attach(ws.asClient());
  return { feed, ws };
}

describe('MarketFeed', () => {
  it('subscribes once per key (ref-counted) and unsubscribes when the last consumer leaves', () => {
    const { feed, ws } = setup();
    const off1 = feed.subscribe('BTCUSDT', '5m', { onCandle: vi.fn() });
    const off2 = feed.subscribe('BTCUSDT', '5m', { onCandle: vi.fn() });
    expect(ws.sent.filter((m) => m.type === 'market.subscribe')).toHaveLength(1);
    off1();
    expect(ws.sent.some((m) => m.type === 'market.unsubscribe')).toBe(false);
    off2();
    expect(ws.sent.at(-1)).toEqual({
      type: 'market.unsubscribe',
      data: { symbol: 'BTCUSDT', timeframe: '5m' },
    });
  });

  it('routes candles by symbol AND timeframe only', () => {
    const { feed, ws } = setup();
    const btc5 = vi.fn();
    const btc1 = vi.fn();
    feed.subscribe('BTCUSDT', '5m', { onCandle: btc5 });
    feed.subscribe('BTCUSDT', '1m', { onCandle: btc1 });
    ws.emit('market.candle', { symbol: 'BTCUSDT', timeframe: '5m', candle: bar(60) });
    ws.emit('market.candle', { symbol: 'ETHUSDT', timeframe: '5m', candle: bar(60) });
    expect(btc5).toHaveBeenCalledOnce();
    expect(btc1).not.toHaveBeenCalled();
  });

  it('drops events for streams nobody listens to anymore', () => {
    const { feed, ws } = setup();
    const handler = vi.fn();
    const off = feed.subscribe('BTCUSDT', '1m', { onCandle: handler });
    off();
    ws.emit('market.candle', { symbol: 'BTCUSDT', timeframe: '1m', candle: bar(60) });
    expect(handler).not.toHaveBeenCalled();
  });

  it('subscribes on connect, resubscribes and requests resync after an app reconnect', () => {
    const feed = new MarketFeed();
    const onResync = vi.fn();
    feed.subscribe('ETHUSDT', '15m', { onCandle: vi.fn(), onResync }); // before the socket exists
    const ws = new FakeRealtime();
    feed.attach(ws.asClient());
    ws.connected();
    expect(ws.sent).toEqual([
      { type: 'market.subscribe', data: { symbol: 'ETHUSDT', timeframe: '15m' } },
    ]);
    expect(onResync).not.toHaveBeenCalled(); // first connect: history not stale

    ws.connected(); // reconnect
    expect(ws.sent.filter((m) => m.type === 'market.subscribe')).toHaveLength(2);
    expect(onResync).toHaveBeenCalledOnce();
  });

  it('delivers stream state, resync, errors, ticks and feed status', () => {
    const { feed, ws } = setup();
    const handlers = { onCandle: vi.fn(), onStream: vi.fn(), onResync: vi.fn(), onError: vi.fn() };
    feed.subscribe('BTCUSDT', '10m', handlers);
    const tick = vi.fn();
    feed.onTick('BTCUSDT', tick);
    const status = vi.fn();
    feed.onStatus(status);

    ws.emit('market.stream', { symbol: 'BTCUSDT', timeframe: '10m', state: 'stale' });
    ws.emit('market.resync', { symbol: 'BTCUSDT', timeframe: '10m', reason: 'reconnect' });
    ws.emit('system.error', { code: 'symbol_unavailable', symbol: 'btcusdt', timeframe: '10m' });
    ws.emit('market.tick', { symbol: 'BTCUSDT', price: '65000.5', timestamp: 't' });
    ws.emit('market.status', { provider: 'bingx', state: 'reconnecting' });

    expect(handlers.onStream).toHaveBeenCalledWith('stale');
    expect(handlers.onResync).toHaveBeenCalledOnce();
    expect(handlers.onError).toHaveBeenCalledWith('symbol_unavailable');
    expect(tick).toHaveBeenCalledWith('65000.5', 't');
    expect(status).toHaveBeenCalledWith('reconnecting');
  });
});
