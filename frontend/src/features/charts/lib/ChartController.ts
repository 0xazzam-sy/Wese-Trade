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
  private gen = 0;

  constructor(
    private readonly series: CandleSeries,
    /** Called after history loads with the number of bars (sets the initial view). */
    private readonly fit: (count: number) => void = () => undefined,
    /**
     * Called on every context change (symbol / timeframe / reload): restores price
     * auto-scale and the time scale. Without it a price axis the user dragged or zoomed
     * keeps the PREVIOUS symbol's range (BTC 85,000 → NEAR 5.3 = blank chart).
     */
    private readonly resetView: () => void = () => undefined,
  ) {}

  /** Generation of the current chart context; stale loads compare against it. */
  get generation(): number {
    return this.gen;
  }

  get hasHistory(): boolean {
    return this.lastTime !== null;
  }

  get latestTime(): number | null {
    return this.lastTime;
  }

  /** True when a candle with this open time is loaded on the chart. */
  hasTime(time: number): boolean {
    return this.times.has(time);
  }

  /**
   * Starts a new chart context: clears candles, restores auto-scale and returns the new
   * generation. Anything loaded for an older generation is refused by setHistory.
   */
  reset(): number {
    this.gen += 1;
    this.times = new Set();
    this.lastTime = null;
    this.series.setData([]);
    this.resetView();
    return this.gen;
  }

  /** Returns the number of bars applied, or -1 when `generation` is stale (ignored). */
  setHistory(bars: readonly CandleBar[], generation: number = this.gen): number {
    if (generation !== this.gen) return -1;
    const normalized = normalizeHistory(bars);
    const data: ChartCandle[] = normalized.map(toChartCandle);
    this.series.setData(data);
    this.times = new Set(normalized.map((b) => b.time));
    this.lastTime = normalized.length ? (normalized[normalized.length - 1]?.time ?? null) : null;
    this.fit(normalized.length);
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
