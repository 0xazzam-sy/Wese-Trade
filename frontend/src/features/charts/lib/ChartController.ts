import type { ISeriesApi, PriceFormat } from 'lightweight-charts';

import type { CandleBar } from '@/types/market';

import { type ChartCandle, normalizeHistory, toChartCandle } from './candles';

/** Minimal series surface used here (keeps the controller unit-testable). */
export type CandleSeries = Pick<ISeriesApi<'Candlestick'>, 'setData' | 'update' | 'applyOptions'>;

export type ApplyResult = 'updated' | 'appended' | 'historical' | 'ignored' | 'gap';

/**
 * Owns the candle data of one chart outside React.
 *
 * Invariants enforced (lightweight-charts would throw otherwise):
 * - history is strictly ascending with unique times
 * - a live bar with the latest time updates in place; a newer time appends
 * - an older bar may only update an existing point (historical update), never insert
 * - nothing is applied before history is loaded for the current symbol/timeframe
 */
export class ChartController {
  private times = new Set<number>();
  private lastTime: number | null = null;

  constructor(
    private readonly series: CandleSeries,
    private readonly fit: () => void = () => undefined,
  ) {}

  get hasHistory(): boolean {
    return this.lastTime !== null;
  }

  get latestTime(): number | null {
    return this.lastTime;
  }

  reset(): void {
    this.times = new Set();
    this.lastTime = null;
    this.series.setData([]);
  }

  setHistory(bars: readonly CandleBar[]): number {
    const normalized = normalizeHistory(bars);
    const data: ChartCandle[] = normalized.map(toChartCandle);
    this.series.setData(data);
    this.times = new Set(normalized.map((b) => b.time));
    this.lastTime = normalized.length ? (normalized[normalized.length - 1]?.time ?? null) : null;
    this.fit();
    return normalized.length;
  }

  applyBar(bar: CandleBar): ApplyResult {
    if (this.lastTime === null) return 'ignored';
    const candle = toChartCandle(bar);
    if (![candle.open, candle.high, candle.low, candle.close].every(Number.isFinite))
      return 'ignored';
    if (bar.time === this.lastTime) {
      this.series.update(candle);
      return 'updated';
    }
    if (bar.time > this.lastTime) {
      this.series.update(candle);
      this.times.add(bar.time);
      this.lastTime = bar.time;
      return 'appended';
    }
    if (this.times.has(bar.time)) {
      this.series.update(candle, true);
      return 'historical';
    }
    return 'gap'; // an older candle we never had: caller should resync history
  }

  setPriceFormat(format: PriceFormat | undefined): void {
    if (format) this.series.applyOptions({ priceFormat: format });
  }
}
