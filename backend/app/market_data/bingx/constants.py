"""BingX API constants. See docs/bingx-market-data.md for the verification status of each."""

from __future__ import annotations

from typing import Final

from app.market_data.timeframes import Timeframe

# REST paths (public market interface; no signature or API key required).
PATH_CONTRACTS: Final = "/openApi/swap/v2/quote/contracts"
PATH_KLINES_V3: Final = "/openApi/swap/v3/quote/klines"
PATH_KLINES_V2: Final = "/openApi/swap/v2/quote/klines"
PATH_TICKER: Final = "/openApi/swap/v2/quote/ticker"
PATH_PREMIUM_INDEX: Final = "/openApi/swap/v2/quote/premiumIndex"
PATH_OPEN_INTEREST: Final = "/openApi/swap/v2/quote/openInterest"
PATH_DEPTH: Final = "/openApi/swap/v2/quote/depth"

KLINE_MAX_LIMIT: Final = 1440  # documented maximum per kline request

# Public market endpoints: documented limit 20 requests / second / IP.
# We stay well below it.
REST_RATE_PER_SECOND: Final = 8.0
REST_BURST: Final = 8
REST_MAX_CONCURRENCY: Final = 4
REST_TIMEOUT_SECONDS: Final = 10.0
REST_MAX_ATTEMPTS: Final = 3
RATE_LIMIT_MIN_COOLDOWN_SECONDS: Final = 5.0

# Business error codes that indicate throttling (HTTP may still be 200).
RATE_LIMIT_CODES: Final = frozenset({100410})

# WebSocket: server pings every ~5s; treat 30s of total silence as a dead socket.
WS_SILENCE_TIMEOUT_SECONDS: Final = 30.0
WS_BACKOFF_BASE_SECONDS: Final = 1.0
WS_BACKOFF_MAX_SECONDS: Final = 60.0
WS_OPEN_TIMEOUT_SECONDS: Final = 10.0

# Native exchange interval names. 10m is intentionally absent (synthetic).
INTERVALS: Final[dict[Timeframe, str]] = {
    Timeframe.M1: "1m",
    Timeframe.M5: "5m",
    Timeframe.M15: "15m",
    Timeframe.M30: "30m",
    Timeframe.H1: "1h",
}
INTERVAL_TO_TIMEFRAME: Final[dict[str, Timeframe]] = {v: k for k, v in INTERVALS.items()}

QUOTE_ASSET: Final = "USDT"
