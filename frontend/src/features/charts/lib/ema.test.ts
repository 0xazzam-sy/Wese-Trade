import { describe, expect, it, vi } from 'vitest';

import type { CandleBar } from '@/types/market';

import { ChartController } from './ChartController';
import { EmaTrack } from './ema';

const bar = (time: number, close: number): CandleBar => ({
  time,
  open: String(close),
  high: String(close + 1),
  low: String(close - 1),
  close: String(close),
  volume: '1',
  is_closed: true,
});

describe('EMA lines', () => {
  it('matches the backend recursion and hides un-warmed points', () => {
    const t = new EmaTrack(3);
    t.reset([10, 11, 12, 13]);
    const k = 2 / 4;
    let v = 10;
    for (const c of [11, 12, 13]) v += k * (c - v);
    const pts = t.points([1, 2, 3, 4]);
    expect(pts.map((p) => p.time)).toEqual([3, 4]); // period 3: first visible at index 2
    expect(pts[1]?.value).toBeCloseTo(v);
  });

  it('incremental update equals a full recompute (append and in-place update)', () => {
    const a = new EmaTrack(20);
    const closes = Array.from({ length: 60 }, (_, i) => 100 + Math.sin(i / 3) * 5);
    a.reset(closes.slice(0, 40));
    for (const c of closes.slice(40)) a.push(c, false);
    a.push(999, true); // forming candle update replaces the last value
    const b = new EmaTrack(20);
    b.reset([...closes.slice(0, 59), 999]);
    const times = closes.map((_, i) => i);
    expect(a.points(times)).toEqual(b.points(times));
  });

  it('the chart controller feeds three EMA series and resets them on a context switch', () => {
    const series = { setData: vi.fn(), update: vi.fn(), applyOptions: vi.fn() };
    const lines = [0, 1, 2].map(() => ({
      setData: vi.fn(),
      update: vi.fn(),
      applyOptions: vi.fn(),
    }));
    const chart = new ChartController(series, undefined, undefined, lines);
    chart.setHistory(Array.from({ length: 250 }, (_, i) => bar(i * 60, 100 + i)));
    expect(lines[0]?.setData.mock.calls[0]?.[0]).toHaveLength(250 - 19);
    expect(lines[2]?.setData.mock.calls[0]?.[0]).toHaveLength(250 - 199);
    chart.applyBar(bar(250 * 60, 400));
    expect(lines[0]?.update).toHaveBeenCalled();
    chart.setEmaVisible(false);
    expect(lines[1]?.applyOptions).toHaveBeenCalledWith({ visible: false });
    chart.reset();
    expect(lines[0]?.setData).toHaveBeenLastCalledWith([]);
  });
});
