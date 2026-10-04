"""Normalization of raw BingX payloads into domain models.

Every function is pure and defensive: malformed items raise `BingXInvalidResponse`
(single objects) or are skipped and counted (lists), never silently "fixed".
"""

from __future__ import annotations

import gzip
import json
import zlib
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.core.logging import get_logger
from app.market_data.bingx.constants import INTERVAL_TO_TIMEFRAME, QUOTE_ASSET
from app.market_data.bingx.exceptions import BingXInvalidResponse
from app.market_data.models import (
    BookTicker,
    Candle,
    FundingInfo,
    MarketSymbol,
    OpenInterest,
    SymbolStatus,
    Ticker,
)
from app.market_data.timeframes import Timeframe

logger = get_logger(__name__)


# --- primitives -------------------------------------------------------------


def to_decimal(value: Any, field: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise BingXInvalidResponse(f"{field}: expected number, got {value!r}")
    try:
        # str() first: avoids binary-float artefacts if BingX ever sends JSON numbers.
        result = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise BingXInvalidResponse(f"{field}: invalid decimal {value!r}") from exc
    if not result.is_finite():
        raise BingXInvalidResponse(f"{field}: non-finite {value!r}")
    return result


def to_optional_decimal(value: Any, field: str) -> Decimal | None:
    if value is None or value == "":
        return None
    return to_decimal(value, field)


def to_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise BingXInvalidResponse(f"{field}: expected int, got bool")
    try:
        return int(str(value))
    except (TypeError, ValueError) as exc:
        raise BingXInvalidResponse(f"{field}: invalid int {value!r}") from exc


def ms_to_datetime(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=UTC)


def normalize_symbol(exchange_symbol: str) -> str:
    """'BTC-USDT' -> 'BTCUSDT'."""
    return exchange_symbol.replace("-", "").upper()


def _require_mapping(raw: Any, what: str) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping):
        raise BingXInvalidResponse(f"{what}: expected object, got {type(raw).__name__}")
    return raw


def as_list(data: Any) -> list[Any]:
    """Some endpoints return an object for one symbol and a list for many."""
    if data is None:
        return []
    if isinstance(data, list):
        return data
    return [data]


# --- contracts ----------------------------------------------------------------


def _truthy_flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes"}


def parse_contract(raw: Any) -> MarketSymbol | None:
    """Return a MarketSymbol for USDT-settled perpetuals; None for other contracts."""
    item = _require_mapping(raw, "contract")
    exchange_symbol = str(item.get("symbol", "")).strip().upper()
    base, sep, quote = exchange_symbol.partition("-")
    currency = str(item.get("currency", quote)).upper()
    if not sep or not base or quote != QUOTE_ASSET or currency != QUOTE_ASSET:
        return None

    price_precision = to_int(item.get("pricePrecision"), "pricePrecision")
    quantity_precision = to_int(item.get("quantityPrecision"), "quantityPrecision")
    if not (0 <= price_precision <= 18 and 0 <= quantity_precision <= 18):
        raise BingXInvalidResponse(f"{exchange_symbol}: precision out of range")

    online = to_int(item.get("status", 0), "status") == 1
    # Newer API revisions add apiStateOpen ("true"/"false"); absent means unknown -> trust status.
    api_open = item.get("apiStateOpen")
    trading_enabled = online and (api_open is None or _truthy_flag(api_open))

    leverages = [
        to_int(item[k], k)
        for k in ("maxLongLeverage", "maxShortLeverage")
        if item.get(k) is not None
    ]
    asset = str(item.get("asset") or base).upper()
    return MarketSymbol(
        symbol=normalize_symbol(exchange_symbol),
        exchange_symbol=exchange_symbol,
        base_asset=asset,
        quote_asset=QUOTE_ASSET,
        display_name=f"{asset}/{QUOTE_ASSET}",
        contract_type="perpetual",
        status=SymbolStatus.ACTIVE if online else SymbolStatus.UNAVAILABLE,
        price_precision=price_precision,
        quantity_precision=quantity_precision,
        # BingX publishes precision, not an explicit tick size: tick = 10^-pricePrecision.
        tick_size=Decimal(1).scaleb(-price_precision),
        step_size=Decimal(1).scaleb(-quantity_precision),
        min_quantity=to_optional_decimal(item.get("tradeMinQuantity"), "tradeMinQuantity"),
        min_notional=to_optional_decimal(item.get("tradeMinUSDT"), "tradeMinUSDT"),
        max_leverage=max(leverages) if leverages else None,
        trading_enabled=trading_enabled,
    )


def parse_contracts(data: Any) -> list[MarketSymbol]:
    if not isinstance(data, list):
        raise BingXInvalidResponse("contracts: expected list")
    symbols: dict[str, MarketSymbol] = {}
    skipped = 0
    for raw in data:
        try:
            parsed = parse_contract(raw)
        except BingXInvalidResponse as exc:
            skipped += 1
            logger.debug("bingx.contract_skipped", extra={"fields": {"reason": str(exc)}})
            continue
        if parsed is None:
            continue
        if parsed.symbol in symbols:
            logger.warning("bingx.duplicate_symbol", extra={"fields": {"symbol": parsed.symbol}})
            continue
        symbols[parsed.symbol] = parsed
    if skipped:
        logger.warning("bingx.contracts_malformed", extra={"fields": {"skipped": skipped}})
    return sorted(symbols.values(), key=lambda s: s.symbol)


# --- candles ------------------------------------------------------------------


def _kline_fields(raw: Any) -> tuple[Any, Any, Any, Any, Any, Any]:
    """Return (time, open, high, low, close, volume) from REST object / array / WS object."""
    if isinstance(raw, Mapping):
        if "o" in raw:  # WebSocket push: {"o","h","l","c","v","T"}
            return (
                raw.get("T"),
                raw.get("o"),
                raw.get("h"),
                raw.get("l"),
                raw.get("c"),
                raw.get("v"),
            )
        return (
            raw.get("time"),
            raw.get("open"),
            raw.get("high"),
            raw.get("low"),
            raw.get("close"),
            raw.get("volume"),
        )
    if isinstance(raw, list) and len(raw) >= 6:  # defensive: [t, o, h, l, c, v, ...]
        return raw[0], raw[1], raw[2], raw[3], raw[4], raw[5]
    raise BingXInvalidResponse("kline: unrecognised shape")


def parse_kline(raw: Any, symbol: str, timeframe: Timeframe, *, now_ms: int) -> Candle:
    t, o, h, low_raw, c, v = _kline_fields(raw)
    timestamp = to_int(t, "kline.time")
    if timestamp <= 0:
        raise BingXInvalidResponse("kline.time must be positive")
    open_price = to_decimal(o, "open")
    high = to_decimal(h, "high")
    low = to_decimal(low_raw, "low")
    close = to_decimal(c, "close")
    volume = to_decimal(v, "volume")
    if min(open_price, high, low, close) <= 0:
        raise BingXInvalidResponse("kline: non-positive price")
    if high < max(open_price, close, low) or low > min(open_price, close):
        raise BingXInvalidResponse("kline: inconsistent OHLC")
    if volume < 0:
        raise BingXInvalidResponse("kline: negative volume")

    # BingX timestamps are the bucket open time (REST) or a time inside the bucket
    # (older WS docs show xx:59.999). Flooring to the bucket handles both.
    open_ms = timeframe.bucket_start_ms(timestamp)
    return Candle(
        symbol=symbol,
        timeframe=timeframe,
        open_time=ms_to_datetime(open_ms),
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=volume,
        # A candle is closed only once its bucket has ended. Never earlier.
        is_closed=open_ms + timeframe.milliseconds <= now_ms,
    )


def parse_klines(data: Any, symbol: str, timeframe: Timeframe, *, now_ms: int) -> list[Candle]:
    """Parse, validate, de-duplicate (last wins) and sort chronologically."""
    by_time: dict[int, Candle] = {}
    skipped = 0
    for raw in as_list(data):
        try:
            candle = parse_kline(raw, symbol, timeframe, now_ms=now_ms)
        except BingXInvalidResponse:
            skipped += 1
            continue
        by_time[candle.open_ms] = candle
    if skipped:
        logger.warning(
            "bingx.klines_malformed",
            extra={"fields": {"symbol": symbol, "timeframe": timeframe.value, "skipped": skipped}},
        )
    return [by_time[k] for k in sorted(by_time)]


# --- tickers / funding / open interest / book -----------------------------------


def parse_ticker(raw: Any, *, now: datetime) -> Ticker | None:
    item = _require_mapping(raw, "ticker")
    exchange_symbol = str(item.get("symbol", "")).upper()
    if not exchange_symbol.endswith(f"-{QUOTE_ASSET}"):
        return None
    close_time = item.get("closeTime")
    return Ticker(
        symbol=normalize_symbol(exchange_symbol),
        last_price=to_decimal(item.get("lastPrice"), "lastPrice"),
        price_change=to_decimal(item.get("priceChange"), "priceChange"),
        price_change_percent=to_decimal(item.get("priceChangePercent"), "priceChangePercent"),
        open_price=to_optional_decimal(item.get("openPrice"), "openPrice"),
        high_24h=to_decimal(item.get("highPrice"), "highPrice"),
        low_24h=to_decimal(item.get("lowPrice"), "lowPrice"),
        volume_24h=to_decimal(item.get("volume"), "volume"),
        quote_volume_24h=to_optional_decimal(item.get("quoteVolume"), "quoteVolume"),
        bid=to_optional_decimal(item.get("bidPrice"), "bidPrice"),
        ask=to_optional_decimal(item.get("askPrice"), "askPrice"),
        timestamp=ms_to_datetime(to_int(close_time, "closeTime")) if close_time else now,
    )


def parse_tickers(data: Any, *, now: datetime) -> list[Ticker]:
    tickers: list[Ticker] = []
    for raw in as_list(data):
        try:
            ticker = parse_ticker(raw, now=now)
        except BingXInvalidResponse:
            continue
        if ticker is not None:
            tickers.append(ticker)
    return tickers


def parse_funding(data: Any, *, now: datetime) -> list[FundingInfo]:
    result: list[FundingInfo] = []
    now_ms = int(now.timestamp() * 1000)
    for raw in as_list(data):
        try:
            item = _require_mapping(raw, "premiumIndex")
            exchange_symbol = str(item.get("symbol", "")).upper()
            if not exchange_symbol.endswith(f"-{QUOTE_ASSET}"):
                continue
            next_raw = item.get("nextFundingTime")
            next_time: datetime | None = None
            if next_raw not in (None, "", 0):
                value = to_int(next_raw, "nextFundingTime")
                # Field is documented as "remaining ms" but examples show an absolute epoch.
                next_time = ms_to_datetime(value if value > 10**12 else now_ms + value)
            result.append(
                FundingInfo(
                    symbol=normalize_symbol(exchange_symbol),
                    funding_rate=to_decimal(item.get("lastFundingRate"), "lastFundingRate"),
                    mark_price=to_optional_decimal(item.get("markPrice"), "markPrice"),
                    index_price=to_optional_decimal(item.get("indexPrice"), "indexPrice"),
                    next_funding_time=next_time,
                    timestamp=now,
                )
            )
        except BingXInvalidResponse:
            continue
    return result


def parse_open_interest(data: Any, symbol: str, *, now: datetime) -> OpenInterest:
    item = _require_mapping(as_list(data)[0] if isinstance(data, list) and data else data, "oi")
    time_raw = item.get("time")
    return OpenInterest(
        symbol=symbol,
        value=to_decimal(item.get("openInterest"), "openInterest"),
        timestamp=ms_to_datetime(to_int(time_raw, "time")) if time_raw else now,
    )


def _best(levels: Any, *, highest: bool) -> tuple[Decimal, Decimal | None] | None:
    parsed: list[tuple[Decimal, Decimal | None]] = []
    for level in levels if isinstance(levels, list) else []:
        if isinstance(level, list) and level:
            qty = to_optional_decimal(level[1], "qty") if len(level) > 1 else None
            parsed.append((to_decimal(level[0], "price"), qty))
        elif isinstance(level, Mapping) and "p" in level:
            parsed.append(
                (to_decimal(level["p"], "price"), to_optional_decimal(level.get("v"), "qty"))
            )
    if not parsed:
        return None
    return max(parsed, key=lambda x: x[0]) if highest else min(parsed, key=lambda x: x[0])


def parse_book_from_depth(data: Any, symbol: str, *, now: datetime) -> BookTicker | None:
    item = _require_mapping(data, "depth")
    bid = _best(item.get("bids"), highest=True)
    ask = _best(item.get("asks"), highest=False)
    if bid is None or ask is None or ask[0] < bid[0]:
        return None
    return BookTicker(
        symbol=symbol, bid=bid[0], bid_qty=bid[1], ask=ask[0], ask_qty=ask[1], timestamp=now
    )


# --- WebSocket frames -------------------------------------------------------------


def decode_frame(frame: bytes | str) -> str:
    """BingX gzip-compresses every frame. Accept plain text too (defensive)."""
    if isinstance(frame, str):
        return frame
    for decoder in (gzip.decompress, zlib.decompress):
        try:
            return decoder(frame).decode("utf-8")
        except (OSError, zlib.error, EOFError, UnicodeDecodeError):
            continue
    return frame.decode("utf-8", errors="replace")


def parse_json(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise BingXInvalidResponse("frame: invalid JSON") from exc


def split_data_type(data_type: str) -> tuple[str, Timeframe] | None:
    """'BTC-USDT@kline_5m' -> ('BTC-USDT', Timeframe.M5); None for other streams."""
    exchange_symbol, sep, stream = data_type.partition("@")
    if not sep or not stream.startswith("kline_"):
        return None
    timeframe = INTERVAL_TO_TIMEFRAME.get(stream.removeprefix("kline_"))
    if timeframe is None:
        return None
    return exchange_symbol.upper(), timeframe


def parse_kline_push(message: Mapping[str, Any], *, now_ms: int) -> list[Candle]:
    """Parse a kline push. `data` may be one object or a list (newer API revisions)."""
    data_type = message.get("dataType")
    if not isinstance(data_type, str):
        return []
    target = split_data_type(data_type)
    if target is None:
        return []
    exchange_symbol, timeframe = target
    symbol = normalize_symbol(exchange_symbol)
    candles: list[Candle] = []
    for raw in as_list(message.get("data")):
        try:
            candles.append(parse_kline(raw, symbol, timeframe, now_ms=now_ms))
        except BingXInvalidResponse:
            logger.debug("bingx.ws_kline_malformed", extra={"fields": {"dataType": data_type}})
    return sorted(candles, key=lambda c: c.open_ms)


def iter_mappings(data: Any) -> Iterable[Mapping[str, Any]]:
    return (item for item in as_list(data) if isinstance(item, Mapping))
