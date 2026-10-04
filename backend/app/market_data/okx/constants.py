"""OKX API constants, verified against official docs and live responses (see docs)."""

from __future__ import annotations

from typing import Final

from app.market_data.timeframes import Timeframe

# REST (public endpoints only).
PATH_TIME: Final = "/api/v5/public/time"
PATH_INSTRUMENTS: Final = "/api/v5/public/instruments"
PATH_CANDLES: Final = "/api/v5/market/candles"
PATH_HISTORY_CANDLES: Final = "/api/v5/market/history-candles"
PATH_TICKER: Final = "/api/v5/market/ticker"
PATH_TICKERS: Final = "/api/v5/market/tickers"
PATH_MARK_PRICE: Final = "/api/v5/public/mark-price"
PATH_FUNDING_RATE: Final = "/api/v5/public/funding-rate"
PATH_OPEN_INTEREST: Final = "/api/v5/public/open-interest"

INST_TYPE: Final = "SWAP"
SETTLE_CCY: Final = "USDT"
INST_SUFFIX: Final = "-USDT-SWAP"

CANDLES_PAGE_LIMIT: Final = 300  # documented maximum per request
CANDLES_RECENT_DEPTH: Final = 1440  # /market/candles reaches back this many rows; older -> history

# Documented limits: candles 40 req/2s, history-candles 20 req/2s, tickers 20 req/2s (per IP).
REST_RATE_PER_SECOND: Final = 8.0
REST_BURST: Final = 8
REST_MAX_CONCURRENCY: Final = 4
REST_TIMEOUT_SECONDS: Final = 10.0
REST_MAX_ATTEMPTS: Final = 3
RATE_LIMIT_MIN_COOLDOWN_SECONDS: Final = 5.0
RATE_LIMIT_CODES: Final = frozenset({"50011", "50061"})  # "Too Many Requests"
UNKNOWN_INSTRUMENT_CODES: Final = frozenset({"51001"})

# WebSocket: the server drops a connection with no data for 30s. We send "ping" after
# PING_AFTER seconds of silence and reconnect if nothing (not even "pong") follows.
WS_PING_AFTER_SECONDS: Final = 20.0
WS_PONG_TIMEOUT_SECONDS: Final = 10.0
WS_BACKOFF_BASE_SECONDS: Final = 1.0
WS_BACKOFF_MAX_SECONDS: Final = 30.0
WS_OPEN_TIMEOUT_SECONDS: Final = 10.0
WS_SUBSCRIBE_BATCH: Final = 50  # args per subscribe request
WS_SUBSCRIBE_DEBOUNCE_SECONDS: Final = 0.15  # coalesce sub/unsub bursts (480 requests/hour limit)

# Native candle channels / REST bars. 10m is intentionally absent (synthetic).
BARS: Final[dict[Timeframe, str]] = {
    Timeframe.M1: "1m",
    Timeframe.M5: "5m",
    Timeframe.M15: "15m",
    Timeframe.M30: "30m",
    Timeframe.H1: "1H",
}
CANDLE_CHANNELS: Final[dict[str, Timeframe]] = {f"candle{bar}": tf for tf, bar in BARS.items()}
CHANNEL_TICKERS: Final = "tickers"
CHANNEL_MARK_PRICE: Final = "mark-price"
