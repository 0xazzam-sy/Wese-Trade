import type { ISeriesApi, LineData, PriceFormat, UTCTimestamp } from 'lightweight-charts';

import type { CandleBar } from '@/types/market';

import { type ChartCandle, normalizeHistory, toChartCandle } from './candles';
import { EMA_PERIODS, EmaTrack } from './ema';

/** Minimal series surface used here (keeps the controller unit-testable). */
export type CandleSeries = Pick<ISeriesApi<'Candlestick'>, 'setData' | 'update' | 'applyOptions'>;

export type ApplyResult = 'updated' | 'appended' | 'historical' | 'ignored' | 'gap';

/** Minimal line-series surface for the EMA lines. */
export type LineSeries = Pick<ISeriesApi<'Line'>, 'setData' | 'update' | 'applyOptions'>;

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
  /** Ordered open times and closes of the loaded bars (EMA input). */
  private order: number[] = [];
  private closes: number[] = [];
  private readonly emas = EMA_PERIODS.map((n) => new EmaTrack(n));

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
    /** EMA 20 / 50 / 200 line series (same order as EMA_PERIODS); optional. */
    private readonly emaLines: readonly LineSeries[] = [],
  ) {}

  private emaData(track: EmaTrack): LineData<UTCTimestamp>[] {
    return track.points(this.order).map((p) => ({ time: p.time as UTCTimestamp, value: p.value }));
  }

  private redrawEmas(): void {
    this.emas.forEach((track, i) => {
      track.reset(this.closes);
      this.emaLines[i]?.setData(this.emaData(track));
    });
  }

  private pushEmas(time: number, close: number, replace: boolean): void {
    this.emas.forEach((track, i) => {
      const value = track.push(close, replace);
      if (track.visible(track.length - 1)) {
        this.emaLines[i]?.update({ time: time as UTCTimestamp, value });
      }
    });
  }

  /** Show or hide the EMA lines (overlay toggle). */
  setEmaVisible(visible: boolean): void {
    for (const line of this.emaLines) line.applyOptions({ visible });
  }

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
    this.order = [];
    this.closes = [];
    this.series.setData([]);
    for (const line of this.emaLines) line.setData([]);
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
    this.order = data.map((c) => c.time);
    this.closes = data.map((c) => c.close);
    this.redrawEmas();
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
      this.closes[this.closes.length - 1] = candle.close;
      this.pushEmas(bar.time, candle.close, true);
      return 'updated';
    }
    if (bar.time > this.lastTime) {
      this.series.update(candle);
      this.times.add(bar.time);
      this.lastTime = bar.time;
      this.order.push(bar.time);
      this.closes.push(candle.close);
      this.pushEmas(bar.time, candle.close, false);
      return 'appended';
    }
    if (this.times.has(bar.time)) {
      this.series.update(candle, true);
      const i = this.order.indexOf(bar.time);
      if (i >= 0) {
        this.closes[i] = candle.close;
        this.redrawEmas();
      }
      return 'historical';
    }
    return 'gap'; // an older candle we never had: caller should resync history
  }

  setPriceFormat(format: PriceFormat | undefined): void {
    if (format) this.series.applyOptions({ priceFormat: format });
  }
}
