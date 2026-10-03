import type { CandlestickData, PriceFormat, UTCTimestamp } from 'lightweight-charts';

import type { CandleDTO, SymbolMeta } from '@/types/market';

/** Chart-ready candle. Numbers are used ONLY at the rendering boundary. */
export type ChartCandle = CandlestickData<UTCTimestamp>;

export function toUtcTimestamp(isoUtc: string): UTCTimestamp {
  return Math.floor(Date.parse(isoUtc) / 1000) as UTCTimestamp;
}

export function candleFromDTO(dto: CandleDTO): ChartCandle {
  return {
    time: toUtcTimestamp(dto.open_time),
    open: Number(dto.open),
    high: Number(dto.high),
    low: Number(dto.low),
    close: Number(dto.close),
  };
}

/** Price axis formatting derived from exchange metadata (never guessed). */
export function priceFormatFor(meta: SymbolMeta | null): PriceFormat | undefined {
  if (!meta) return undefined;
  return { type: 'price', precision: meta.pricePrecision, minMove: Number(meta.tickSize) };
}
