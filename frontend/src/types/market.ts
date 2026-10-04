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

/** Decimal values are transported as strings and parsed only for display. */
export type DecimalString = string;

export interface MarketSymbol {
  symbol: SymbolCode;
  base_asset: string;
  quote_asset: string;
  display_name: string;
  contract_type: string;
  status: 'active' | 'unavailable' | 'delisted';
  price_precision: number;
  quantity_precision: number;
  tick_size: DecimalString;
  step_size: DecimalString;
  min_quantity: DecimalString | null;
  min_notional: DecimalString | null;
  max_leverage: number | null;
  trading_enabled: boolean;
}

export interface SymbolList {
  items: MarketSymbol[];
  total: number;
  default_symbol: SymbolCode | null;
  refreshed_at: string | null;
}

export interface Ticker {
  symbol: SymbolCode;
  last_price: DecimalString;
  price_change: DecimalString;
  price_change_percent: DecimalString;
  open_price: DecimalString | null;
  high_24h: DecimalString;
  low_24h: DecimalString;
  volume_24h: DecimalString;
  quote_volume_24h: DecimalString | null;
  bid: DecimalString | null;
  ask: DecimalString | null;
  timestamp: string;
}

export interface TickerList {
  items: Ticker[];
  fetched_at: string;
}

/** One candle as sent by the backend (REST history and `market.candle`). */
export interface CandleBar {
  /** UTC epoch seconds of the candle open. */
  time: number;
  open: DecimalString;
  high: DecimalString;
  low: DecimalString;
  close: DecimalString;
  volume: DecimalString;
  is_closed: boolean;
}

export interface CandleList {
  symbol: SymbolCode;
  timeframe: Timeframe;
  candles: CandleBar[];
}

export interface SymbolDetails {
  symbol: MarketSymbol;
  ticker: Ticker | null;
  funding: {
    funding_rate: DecimalString;
    mark_price: DecimalString | null;
    index_price: DecimalString | null;
    next_funding_time: string | null;
  } | null;
  open_interest: { value: DecimalString; timestamp: string } | null;
  book: { bid: DecimalString; ask: DecimalString; spread: DecimalString } | null;
}

/** Exchange feed state (market.status). */
export type MarketFeedState =
  'connected' | 'connecting' | 'reconnecting' | 'degraded' | 'disconnected';

/** Per-stream state (market.stream). */
export type StreamState = 'live' | 'stale' | 'reconnecting' | 'unavailable';

export interface MarketHealth {
  provider: string;
  state: MarketFeedState;
  rest_reachable: boolean | null;
  ws_state: string;
  reconnect_count: number;
  symbol_count: number;
  active_streams: string[];
  stale_streams: string[];
  last_metadata_refresh_at: string | null;
}
