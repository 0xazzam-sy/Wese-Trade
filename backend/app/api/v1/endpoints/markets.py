"""Market data routes. Thin: all data comes from MarketDataEngine services, never the exchange."""

from __future__ import annotations

import contextlib
from dataclasses import replace
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import Resources, get_current_user
from app.core.logging import get_logger
from app.market_data.engine import MarketDataEngine
from app.market_data.exceptions import (
    MarketDataError,
    ProviderRateLimited,
    SymbolUnavailable,
    UnknownSymbol,
)
from app.market_data.timeframes import Timeframe
from app.schemas.market import (
    BookOut,
    CandleList,
    CandleOut,
    FundingOut,
    OpenInterestOut,
    SymbolDetails,
    SymbolList,
    SymbolOut,
    TickerList,
    TickerOut,
)
from app.utils.time import utc_now

router = APIRouter(prefix="/markets", tags=["markets"], dependencies=[Depends(get_current_user)])
logger = get_logger(__name__)


def _engine(resources: Resources) -> MarketDataEngine:
    if resources.market is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="market_data_disabled")
    return resources.market


Engine = Annotated[MarketDataEngine, Depends(_engine)]


def _ready(engine: MarketDataEngine) -> None:
    if not engine.symbols.loaded:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="market_data_loading")


def _translate(exc: MarketDataError) -> HTTPException:
    if isinstance(exc, UnknownSymbol):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail="unknown_symbol")
    if isinstance(exc, SymbolUnavailable):
        return HTTPException(status.HTTP_409_CONFLICT, detail="symbol_unavailable")
    if isinstance(exc, ProviderRateLimited):
        return HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="market_data_rate_limited",
            headers={"Retry-After": str(int(exc.retry_after) + 1)},
        )
    logger.warning("market.request_failed", extra={"fields": {"error": str(exc)}})
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="market_data_unavailable")


@router.get("/health")
async def market_health(engine: Engine) -> dict[str, Any]:
    return engine.health_snapshot()


@router.get("/status")
async def market_status(engine: Engine) -> dict[str, Any]:
    return {"module": "markets", "available": engine.symbols.loaded, "state": engine.health.overall}


@router.get("/symbols", response_model=SymbolList)
async def list_symbols(
    engine: Engine,
    search: Annotated[str | None, Query(max_length=32)] = None,
    active_only: bool = True,
    limit: Annotated[int, Query(ge=1, le=5000)] = 5000,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SymbolList:
    _ready(engine)
    items = engine.symbols.list(search=search, active_only=active_only)
    return SymbolList(
        items=[SymbolOut.of(s) for s in items[offset : offset + limit]],
        total=len(items),
        default_symbol=engine.symbols.default_symbol(),
        refreshed_at=engine.health.last_metadata_refresh_at,
    )


@router.get("/tickers", response_model=TickerList)
async def list_tickers(engine: Engine) -> TickerList:
    try:
        tickers = await engine.tickers.tickers()
    except MarketDataError as exc:
        raise _translate(exc) from exc
    return TickerList(items=[TickerOut.of(t) for t in tickers.values()], fetched_at=utc_now())


def _parse_before(before: int | None) -> datetime | None:
    if before is None:
        return None
    seconds = before / 1000 if before > 10**11 else before  # accept s or ms epoch
    return datetime.fromtimestamp(seconds, tz=UTC)


@router.get("/{symbol}/candles", response_model=CandleList)
async def get_candles(
    symbol: str,
    engine: Engine,
    timeframe: Timeframe,
    limit: Annotated[int, Query(ge=1, le=1000)] = 500,
    before: Annotated[int | None, Query(ge=0, description="UTC epoch (s or ms), exclusive")] = None,
) -> CandleList:
    _ready(engine)
    try:
        market = engine.symbols.get(symbol)
        if before is None:
            market = engine.symbols.require_active(symbol)
        candles = await engine.candles.history(
            market, timeframe, limit=limit, before=_parse_before(before)
        )
    except MarketDataError as exc:
        raise _translate(exc) from exc
    return CandleList(
        symbol=market.symbol,
        timeframe=timeframe.value,
        candles=[
            CandleOut(
                time=c.open_ms // 1000,
                open=c.open,
                high=c.high,
                low=c.low,
                close=c.close,
                volume=c.volume,
                is_closed=c.is_closed,
            )
            for c in candles
        ],
    )


@router.get("/{symbol}/details", response_model=SymbolDetails)
async def get_details(symbol: str, engine: Engine) -> SymbolDetails:
    """Instrument metadata + 24h ticker + funding + open interest + best bid/ask.
    Each part is optional: one failing source never fails the whole response."""
    _ready(engine)
    try:
        market = engine.symbols.get(symbol)
    except MarketDataError as exc:
        raise _translate(exc) from exc

    ticker = funding = open_interest = book = None
    with contextlib.suppress(MarketDataError):
        found = (await engine.tickers.tickers()).get(market.symbol)
        ticker = TickerOut.of(found) if found else None
    with contextlib.suppress(MarketDataError):
        info = (await engine.tickers.funding()).get(market.symbol)
        mark = await engine.tickers.mark_price(market.symbol)
        if info is not None:
            funding = FundingOut.of(replace(info, mark_price=mark[0] if mark else None))
    with contextlib.suppress(MarketDataError):
        open_interest = OpenInterestOut.of(await engine.tickers.open_interest(market))
    with contextlib.suppress(MarketDataError):
        best = await engine.tickers.book(market)
        book = BookOut.of(best) if best else None
    return SymbolDetails(
        symbol=SymbolOut.of(market),
        ticker=ticker,
        funding=funding,
        open_interest=open_interest,
        book=book,
    )
