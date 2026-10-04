import type { CandlestickData, PriceFormat, UTCTimestamp } from 'lightweight-charts';

import type { CandleBar, MarketSymbol } from '@/types/market';

/** Chart-ready candle. Numbers are used ONLY at the rendering boundary. */
export type ChartCandle = CandlestickData<UTCTimestamp>;

export function toChartCandle(bar: CandleBar): ChartCandle {
  return {
    time: bar.time as UTCTimestamp,
    open: Number(bar.open),
    high: Number(bar.high),
    low: Number(bar.low),
    close: Number(bar.close),
  };
}

/**
 * Normalize REST history for the chart: strictly ascending, unique times (last wins),
 * malformed rows dropped. lightweight-charts requires this ordering.
 */
export function normalizeHistory(bars: readonly CandleBar[]): CandleBar[] {
  const byTime = new Map<number, CandleBar>();
  for (const bar of bars) {
    if (
      Number.isFinite(bar.time) &&
      [bar.open, bar.high, bar.low, bar.close].every((v) => Number.isFinite(Number(v)))
    ) {
      byTime.set(bar.time, bar);
    }
  }
  return [...byTime.values()].sort((a, b) => a.time - b.time);
}

/** Price axis formatting derived from exchange metadata (never guessed). */
export function priceFormatFor(meta: MarketSymbol | null | undefined): PriceFormat | undefined {
  if (!meta) return undefined;
  return { type: 'price', precision: meta.price_precision, minMove: Number(meta.tick_size) };
}
