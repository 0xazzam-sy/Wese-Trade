/** Supported analysis timeframes (wire format matches the backend `Timeframe` enum). */
export type Timeframe = '1m' | '5m' | '10m' | '15m' | '30m' | '1h';

export interface TimeframeOption {
  value: Timeframe;
  /** Arabic short label shown in the UI. */
  label: string;
  seconds: number;
}

export const TIMEFRAMES: readonly TimeframeOption[] = [
  { value: '1m', label: '1د', seconds: 60 },
  { value: '5m', label: '5د', seconds: 300 },
  { value: '10m', label: '10د', seconds: 600 },
  { value: '15m', label: '15د', seconds: 900 },
  { value: '30m', label: '30د', seconds: 1800 },
  { value: '1h', label: '1س', seconds: 3600 },
];

/** Normalized display symbol, e.g. "BTCUSDT". */
export type SymbolCode = string;

/**
 * Symbol metadata from the exchange. Price precision and tick size MUST come from here,
 * never from assumptions in the UI. Decimal values are transported as strings.
 */
export interface SymbolMeta {
  symbol: SymbolCode;
  baseAsset: string;
  quoteAsset: string;
  tickSize: string;
  pricePrecision: number;
}

/**
 * Candle as delivered by the backend (future `market.candle` event / REST).
 * Prices are decimal strings to avoid float precision loss in transport.
 */
export interface CandleDTO {
  symbol: SymbolCode;
  timeframe: Timeframe;
  open_time: string; // UTC ISO-8601
  open: string;
  high: string;
  low: string;
  close: string;
  volume: string;
  is_closed: boolean;
}
