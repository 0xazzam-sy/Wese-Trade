import { describe, expect, it } from 'vitest';

import { evaluation, signal } from '@/test/signalFixture';

import { applySignalEvent } from './reduce';

const KEY = { symbol: 'BTCUSDT', timeframe: '15m' };
const base = { symbol: 'BTCUSDT', timeframe: '15m' };

describe('applySignalEvent', () => {
  it('ignores events for another stream', () => {
    const out = applySignalEvent(
      null,
      'signal.confirmed',
      { ...base, timeframe: '1h', signal: signal() },
      KEY,
    );
    expect(out).toBeNull();
  });

  it('confirmed -> active; developing is cleared', () => {
    let v = applySignalEvent(
      null,
      'signal.developing',
      { ...base, evaluation: evaluation({ developing: true, signal_class: 'BUY' }) },
      KEY,
    );
    expect(v?.developing?.signal_class).toBe('BUY');
    v = applySignalEvent(v, 'signal.confirmed', { ...base, signal: signal() }, KEY);
    expect(v?.active?.id).toBe('sig-1');
    expect(v?.developing).toBeNull();
  });

  it('updated lifecycle replaces the active signal; closed clears it', () => {
    let v = applySignalEvent(null, 'signal.confirmed', { ...base, signal: signal() }, KEY);
    v = applySignalEvent(
      v,
      'signal.updated',
      { ...base, signal: signal({ targets_hit: 1, state: 'tp1_hit' }) },
      KEY,
    );
    expect(v?.active?.targets_hit).toBe(1);
    v = applySignalEvent(
      v,
      'signal.closed',
      { ...base, signal: signal({ state: 'stopped' }) },
      KEY,
    );
    expect(v?.active).toBeNull();
    expect(v?.lastClosed?.state).toBe('stopped');
  });

  it('a final state in signal.updated also clears the active signal', () => {
    let v = applySignalEvent(null, 'signal.confirmed', { ...base, signal: signal() }, KEY);
    v = applySignalEvent(
      v,
      'signal.updated',
      { ...base, signal: signal({ state: 'tp3_hit' }) },
      KEY,
    );
    expect(v?.active).toBeNull();
  });

  it('drops an older closed-candle evaluation', () => {
    let v = applySignalEvent(
      null,
      'signal.updated',
      { ...base, evaluation: evaluation({ candle_time: 200 }) },
      KEY,
    );
    v = applySignalEvent(
      v,
      'signal.updated',
      { ...base, evaluation: evaluation({ candle_time: 100, score: 5 }) },
      KEY,
    );
    expect(v?.evaluation?.candle_time).toBe(200);
  });

  it('applies the full state snapshot sent on subscribe', () => {
    const v = applySignalEvent(
      null,
      'signal.updated',
      {
        ...base,
        evaluation: evaluation(),
        developing: null,
        active: signal(),
        last_confirmed: signal(),
      },
      KEY,
    );
    expect(v?.active?.id).toBe('sig-1');
    expect(v?.evaluation?.signal_class).toBe('NEUTRAL');
  });
});
