import { describe, expect, it, vi } from 'vitest';

import { bar } from '@/test/fakeRealtime';

import { ChartController } from './ChartController';

function setup() {
  const series = { setData: vi.fn(), update: vi.fn(), applyOptions: vi.fn() };
  const fit = vi.fn();
  return { series, fit, chart: new ChartController(series, fit) };
}

describe('ChartController', () => {
  it('ignores live bars until history is loaded', () => {
    const { chart, series } = setup();
    expect(chart.applyBar(bar(60))).toBe('ignored');
    expect(series.update).not.toHaveBeenCalled();
  });

  it('sorts and de-duplicates history, then fits content', () => {
    const { chart, series, fit } = setup();
    chart.setHistory([bar(120), bar(60), bar(120, '101'), { ...bar(180), close: 'NaN' }]);
    const data = series.setData.mock.calls[0]?.[0] as { time: number; close: number }[];
    expect(data.map((d) => d.time)).toEqual([60, 120]);
    expect(data[1]?.close).toBe(101);
    expect(chart.latestTime).toBe(120);
    expect(fit).toHaveBeenCalledOnce();
  });

  it('updates the current candle in place and appends at rollover', () => {
    const { chart, series } = setup();
    chart.setHistory([bar(60), bar(120)]);
    expect(chart.applyBar(bar(120, '105'))).toBe('updated');
    expect(chart.applyBar(bar(180, '106'))).toBe('appended');
    expect(chart.latestTime).toBe(180);
    expect(series.update).toHaveBeenCalledTimes(2);
    expect(series.update.mock.calls[0]?.[1]).toBeUndefined();
  });

  it('never inserts out-of-order points; existing older points use historical update', () => {
    const { chart, series } = setup();
    chart.setHistory([bar(60), bar(120), bar(180)]);
    expect(chart.applyBar(bar(120, '99', true))).toBe('historical');
    expect(series.update).toHaveBeenLastCalledWith(expect.objectContaining({ time: 120 }), true);
    expect(chart.applyBar(bar(90))).toBe('gap'); // never seen -> caller resyncs
  });

  it('reset clears all data (symbol/timeframe switch)', () => {
    const { chart, series } = setup();
    chart.setHistory([bar(60)]);
    chart.reset();
    expect(series.setData).toHaveBeenLastCalledWith([]);
    expect(chart.hasHistory).toBe(false);
    expect(chart.applyBar(bar(120))).toBe('ignored');
  });
});
