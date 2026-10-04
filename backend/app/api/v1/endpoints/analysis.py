"""Market intelligence routes (Phase 3). Analysis only — no signals, entries, stops or targets."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.analysis.service import AnalysisService
from app.api.deps import Resources, get_current_user
from app.api.v1.endpoints.markets import _translate
from app.market_data.exceptions import MarketDataError
from app.market_data.timeframes import Timeframe

router = APIRouter(prefix="/analysis", tags=["analysis"], dependencies=[Depends(get_current_user)])


def _service(resources: Resources) -> AnalysisService:
    if resources.analysis is None or resources.market is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="market_data_disabled")
    if not resources.market.symbols.loaded:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="market_data_loading")
    return resources.analysis


Service = Annotated[AnalysisService, Depends(_service)]


@router.get("/health")
async def analysis_health(service: Service) -> dict[str, Any]:
    return service.health()


@router.get("/{symbol}")
async def get_analysis(symbol: str, timeframe: Timeframe, service: Service) -> dict[str, Any]:
    """Latest AnalysisSnapshot (`analysis_ready=false` with a reason if history is short)."""
    try:
        market = service.market.symbols.require_active(symbol)
        return await service.latest(market.symbol, timeframe)
    except MarketDataError as exc:
        raise _translate(exc) from exc


@router.get("/{symbol}/history")
async def get_analysis_history(
    symbol: str,
    timeframe: Timeframe,
    service: Service,
    limit: Annotated[int, Query(ge=1, le=300)] = 100,
) -> dict[str, Any]:
    """Compact per-candle feature rows + confirmed structure events/sweeps (max 300 rows)."""
    try:
        market = service.market.symbols.require_active(symbol)
        return await service.history(market.symbol, timeframe, limit)
    except MarketDataError as exc:
        raise _translate(exc) from exc
