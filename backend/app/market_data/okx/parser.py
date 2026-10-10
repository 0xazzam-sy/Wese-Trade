"""Normalization of raw OKX payloads into domain models (pure, defensive functions)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.core.logging import get_logger
from app.market_data.exceptions import InvalidProviderResponse
from app.market_data.models import (
    BookTicker,
    Candle,
    FundingInfo,
    LiveQuote,
    MarketSymbol,
    OpenInterest,
    SymbolStatus,
    Ticker,
)
from app.market_data.okx.constants import CANDLE_CHANNELS, INST_SUFFIX, INST_TYPE, SETTLE_CCY
from app.market_data.timeframes import Timeframe

logger = get_logger(__name__)


# --- primitives ------------------------------------------------------------------


def to_decimal(value: Any, field: str) -> Decimal:
    if isinstance(value, bool) or value is None or value == "":
        raise InvalidProviderResponse(f"{field}: expected number, got {value!r}")
    try:
        result = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise InvalidProviderResponse(f"{field}: invalid decimal {value!r}") from exc
    if not result.is_finite():
        raise InvalidProviderResponse(f"{field}: non-finite {value!r}")
    return result


def to_optional_decimal(value: Any, field: str) -> Decimal | None:
    if value is None or value == "":
        return None
    return to_decimal(value, field)


def to_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise InvalidProviderResponse(f"{field}: expected int, got bool")
    try:
        return int(str(value))
    except (TypeError, ValueError) as exc:
        raise InvalidProviderResponse(f"{field}: invalid int {value!r}") from exc


def ms_to_datetime(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=UTC)


def _mapping(raw: Any, what: str) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping):
        raise InvalidProviderResponse(f"{what}: expected object, got {type(raw).__name__}")
    return raw


def as_list(data: Any) -> list[Any]:
    if data is None:
        return []
    return data if isinstance(data, list) else [data]


# --- symbols ---------------------------------------------------------------------


def to_symbol(inst_id: str) -> str:
    """'BTC-USDT-SWAP' -> 'BTCUSDT'."""
    return inst_id.upper().removesuffix("-SWAP").replace("-", "")


def to_inst_id(symbol: str) -> str:
    """'BTCUSDT' -> 'BTC-USDT-SWAP' (USDT-margined swaps only)."""
    base = symbol.upper().removesuffix(SETTLE_CCY)
    return f"{base}{INST_SUFFIX}"


def is_target_instrument(inst_id: str) -> bool:
    return inst_id.upper().endswith(INST_SUFFIX)


def _decimals(step: Decimal) -> int:
    exponent = step.normalize().as_tuple().exponent
    return max(0, -exponent) if isinstance(exponent, int) else 0


def parse_instrument(raw: Any) -> MarketSymbol | None:
    """MarketSymbol for USDT-settled linear perpetual swaps; None for anything else."""
    item = _mapping(raw, "instrument")
    inst_id = str(item.get("instId", "")).upper()
    if (
        item.get("instType") != INST_TYPE
        or item.get("settleCcy") != SETTLE_CCY
        or item.get("ctType") not in (None, "", "linear")
        or not is_target_instrument(inst_id)
    ):
        return None
    tick = to_decimal(item.get("tickSz"), "tickSz")
    lot = to_decimal(item.get("lotSz"), "lotSz")
    if tick <= 0 or lot <= 0:
        raise InvalidProviderResponse(f"{inst_id}: non-positive tickSz/lotSz")
    state = str(item.get("state", ""))
    base = inst_id.removesuffix(INST_SUFFIX)
    lever = item.get("lever")
    return MarketSymbol(
        symbol=to_symbol(inst_id),
        exchange_symbol=inst_id,
        base_asset=base,
        quote_asset=SETTLE_CCY,
        display_name=f"{base}/{SETTLE_CCY}",
        contract_type="perpetual",
        # live = trading; suspend / preopen / test = listed but not tradable now.
        status=SymbolStatus.ACTIVE if state == "live" else SymbolStatus.UNAVAILABLE,
        price_precision=_decimals(tick),
        quantity_precision=_decimals(lot),
        tick_size=tick,  # exact exchange filter, never derived from precision
        step_size=lot,
        min_quantity=to_optional_decimal(item.get("minSz"), "minSz"),
        min_notional=None,  # OKX does not publish a minimum notional for swaps
        max_leverage=to_int(lever, "lever") if lever not in (None, "") else None,
        trading_enabled=state == "live",
        contract_value=to_optional_decimal(item.get("ctVal"), "ctVal"),
        contract_value_currency=str(item.get("ctValCcy") or "") or None,
        category=str(item.get("instCategory") or "1"),
    )


def parse_instruments(data: Any) -> list[MarketSymbol]:
    if not isinstance(data, list):
        raise InvalidProviderResponse("instruments: expected list")
    symbols: dict[str, MarketSymbol] = {}
    skipped = 0
    for raw in data:
        try:
            parsed = parse_instrument(raw)
        except InvalidProviderResponse:
            skipped += 1
            continue
        if parsed is None:
            continue
        if parsed.symbol in symbols:
            logger.warning("okx.duplicate_symbol", extra={"fields": {"symbol": parsed.symbol}})
            continue
        symbols[parsed.symbol] = parsed
    if skipped:
        logger.warning("okx.instruments_malformed", extra={"fields": {"skipped": skipped}})
    return sorted(symbols.values(), key=lambda s: s.symbol)


# --- candles ---------------------------------------------------------------------


def parse_candle_row(raw: Any, symbol: str, timeframe: Timeframe) -> Candle:
    """OKX row: [ts, o, h, l, c, vol(contracts), volCcy(base), volCcyQuote(quote), confirm]."""
    if not isinstance(raw, list) or len(raw) < 9:
        raise InvalidProviderResponse("candle: expected 9-field array")
    timestamp = to_int(raw[0], "ts")
    open_price, high, low, close = (to_decimal(raw[i], n) for i, n in enumerate("ohlc", start=1))
    volume = to_decimal(raw[6], "volCcy")
    quote_volume = to_optional_decimal(raw[7], "volCcyQuote")
    confirm = str(raw[8])
    if confirm not in ("0", "1"):
        raise InvalidProviderResponse(f"candle: invalid confirm flag {confirm!r}")
    if timestamp <= 0 or timestamp % timeframe.milliseconds:
        raise InvalidProviderResponse("candle: timestamp not aligned to the bar")
    if min(open_price, high, low, close) <= 0:
        raise InvalidProviderResponse("candle: non-positive price")
    if high < max(open_price, close, low) or low > min(open_price, close):
        raise InvalidProviderResponse("candle: inconsistent OHLC")
    if volume < 0 or (quote_volume is not None and quote_volume < 0):
        raise InvalidProviderResponse("candle: negative volume")
    return Candle(
        symbol=symbol,
        timeframe=timeframe,
        open_time=ms_to_datetime(timestamp),
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=volume,  # base-currency volume (e.g. BTC), comparable across contract sizes
        quote_volume=quote_volume,
        is_closed=confirm == "1",  # OKX's explicit close flag
    )


def parse_candles(data: Any, symbol: str, timeframe: Timeframe) -> list[Candle]:
    """Parse, validate, de-duplicate (closed beats forming) and sort chronologically."""
    by_time: dict[int, Candle] = {}
    skipped = 0
    for raw in as_list(data):
        try:
            candle = parse_candle_row(raw, symbol, timeframe)
        except InvalidProviderResponse:
            skipped += 1
            continue
        existing = by_time.get(candle.open_ms)
        if existing is None or candle.is_closed or not existing.is_closed:
            by_time[candle.open_ms] = candle
    if skipped:
        logger.warning(
            "okx.candles_malformed",
            extra={"fields": {"symbol": symbol, "timeframe": timeframe.value, "skipped": skipped}},
        )
    return [by_time[k] for k in sorted(by_time)]


# --- tickers / funding / mark / open interest -------------------------------------


def parse_ticker(raw: Any) -> Ticker | None:
    item = _mapping(raw, "ticker")
    inst_id = str(item.get("instId", "")).upper()
    if not is_target_instrument(inst_id):
        return None
    last = to_decimal(item.get("last"), "last")
    open_24h = to_decimal(item.get("open24h"), "open24h")
    change = last - open_24h
    return Ticker(
        symbol=to_symbol(inst_id),
        last_price=last,
        price_change=change,
        price_change_percent=(change / open_24h * 100) if open_24h > 0 else Decimal(0),
        open_price=open_24h,
        high_24h=to_decimal(item.get("high24h"), "high24h"),
        low_24h=to_decimal(item.get("low24h"), "low24h"),
        # For SWAP, volCcy24h is in the base currency (e.g. BTC); vol24h is in contracts.
        volume_24h=to_decimal(item.get("volCcy24h"), "volCcy24h"),
        quote_volume_24h=None,  # not provided for swaps; never estimated
        bid=to_optional_decimal(item.get("bidPx"), "bidPx"),
        ask=to_optional_decimal(item.get("askPx"), "askPx"),
        timestamp=ms_to_datetime(to_int(item.get("ts"), "ts")),
    )


def parse_tickers(data: Any) -> list[Ticker]:
    result: list[Ticker] = []
    for raw in as_list(data):
        try:
            ticker = parse_ticker(raw)
        except InvalidProviderResponse:
            continue
        if ticker is not None:
            result.append(ticker)
    return result


def parse_book(raw: Any) -> BookTicker | None:
    item = _mapping(raw, "ticker")
    bid = to_optional_decimal(item.get("bidPx"), "bidPx")
    ask = to_optional_decimal(item.get("askPx"), "askPx")
    if bid is None or ask is None or ask < bid:
        return None
    return BookTicker(
        symbol=to_symbol(str(item.get("instId", ""))),
        bid=bid,
        bid_qty=to_optional_decimal(item.get("bidSz"), "bidSz"),
        ask=ask,
        ask_qty=to_optional_decimal(item.get("askSz"), "askSz"),
        timestamp=ms_to_datetime(to_int(item.get("ts"), "ts")),
    )


def parse_mark_prices(data: Any) -> dict[str, tuple[Decimal, datetime]]:
    result: dict[str, tuple[Decimal, datetime]] = {}
    for raw in as_list(data):
        try:
            item = _mapping(raw, "mark-price")
            inst_id = str(item.get("instId", "")).upper()
            if is_target_instrument(inst_id):
                result[to_symbol(inst_id)] = (
                    to_decimal(item.get("markPx"), "markPx"),
                    ms_to_datetime(to_int(item.get("ts"), "ts")),
                )
        except InvalidProviderResponse:
            continue
    return result


def parse_funding(data: Any, *, now: datetime) -> list[FundingInfo]:
    """`fundingTime` is the settlement time of the current rate (i.e. the NEXT funding event);
    OKX's `nextFundingTime` is the settlement after that."""
    result: list[FundingInfo] = []
    for raw in as_list(data):
        try:
            item = _mapping(raw, "funding")
            inst_id = str(item.get("instId", "")).upper()
            if not is_target_instrument(inst_id):
                continue
            funding_time = item.get("fundingTime")
            result.append(
                FundingInfo(
                    symbol=to_symbol(inst_id),
                    funding_rate=to_decimal(item.get("fundingRate"), "fundingRate"),
                    mark_price=None,
                    index_price=None,
                    next_funding_time=ms_to_datetime(to_int(funding_time, "fundingTime"))
                    if funding_time not in (None, "")
                    else None,
                    timestamp=now,
                )
            )
        except InvalidProviderResponse:
            continue
    return result


def parse_open_interest(data: Any, symbol: str) -> OpenInterest:
    rows = as_list(data)
    if not rows:
        raise InvalidProviderResponse("open-interest: empty")
    item = _mapping(rows[0], "open-interest")
    return OpenInterest(
        symbol=symbol,
        contracts=to_optional_decimal(item.get("oi"), "oi"),
        base=to_optional_decimal(item.get("oiCcy"), "oiCcy"),
        usd=to_optional_decimal(item.get("oiUsd"), "oiUsd"),
        timestamp=ms_to_datetime(to_int(item.get("ts"), "ts")),
    )


# --- WebSocket ---------------------------------------------------------------------


def parse_candle_push(message: Mapping[str, Any]) -> list[Candle]:
    arg = message.get("arg")
    if not isinstance(arg, Mapping):
        return []
    timeframe = CANDLE_CHANNELS.get(str(arg.get("channel", "")))
    inst_id = str(arg.get("instId", "")).upper()
    if timeframe is None or not is_target_instrument(inst_id):
        return []
    return parse_candles(message.get("data"), to_symbol(inst_id), timeframe)


def parse_quote_push(message: Mapping[str, Any]) -> list[LiveQuote]:
    """`tickers` (last, bid, ask) and `mark-price` channel pushes."""
    arg = message.get("arg")
    if not isinstance(arg, Mapping):
        return []
    channel = arg.get("channel")
    quotes: list[LiveQuote] = []
    for raw in as_list(message.get("data")):
        try:
            item = _mapping(raw, "quote")
            inst_id = str(item.get("instId") or arg.get("instId", "")).upper()
            if not is_target_instrument(inst_id):
                continue
            ts = ms_to_datetime(to_int(item.get("ts"), "ts"))
            if channel == "tickers":
                quotes.append(
                    LiveQuote(
                        symbol=to_symbol(inst_id),
                        timestamp=ts,
                        last=to_optional_decimal(item.get("last"), "last"),
                        bid=to_optional_decimal(item.get("bidPx"), "bidPx"),
                        ask=to_optional_decimal(item.get("askPx"), "askPx"),
                    )
                )
            elif channel == "mark-price":
                quotes.append(
                    LiveQuote(
                        symbol=to_symbol(inst_id),
                        timestamp=ts,
                        mark=to_decimal(item.get("markPx"), "markPx"),
                    )
                )
        except InvalidProviderResponse:
            continue
    return quotes
