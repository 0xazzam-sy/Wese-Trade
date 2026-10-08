"""Execution timing routes (v1.1): 1m / 5m / 10m entry timing for active Strategy 4.2 setups.

Read-only. There are no order or exchange-execution endpoints: Wese Trade never places
trades; the user executes manually.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import Resources, get_current_user
from app.api.v1.endpoints.markets import _translate
from app.execution.models import EXECUTION_TIMEFRAMES
from app.execution.service import ExecutionService
from app.market_data.exceptions import MarketDataError
from app.market_data.timeframes import Timeframe

router = APIRouter(
    prefix="/execution", tags=["execution"], dependencies=[Depends(get_current_user)]
)


def _service(resources: Resources) -> ExecutionService:
    if resources.execution is None or resources.market is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="market_data_disabled")
    if not resources.market.symbols.loaded:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="market_data_loading")
    return resources.execution


Service = Annotated[ExecutionService, Depends(_service)]


def _timeframe(timeframe: Timeframe) -> Timeframe:
    if timeframe.value not in EXECUTION_TIMEFRAMES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail="not_an_execution_timeframe"
        )
    return timeframe


@router.get("/health")
async def execution_health(service: Service) -> dict[str, Any]:
    return service.health()


@router.get("/{symbol}")
async def execution_state(symbol: str, timeframe: Timeframe, service: Service) -> dict[str, Any]:
    """Current execution decision, plan, parent link, markers and overlay of one stream."""
    tf = _timeframe(timeframe)
    try:
        market = service.market.symbols.require_active(symbol)
    except MarketDataError as exc:
        raise _translate(exc) from exc
    return service.state((market.symbol, tf))


@router.get("/{symbol}/history")
async def execution_history(
    symbol: str,
    timeframe: Timeframe,
    service: Service,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict[str, Any]:
    tf = _timeframe(timeframe)
    items = await service.signals(symbol.upper(), tf.value, limit)
    return {"symbol": symbol.upper(), "timeframe": tf.value, "items": items}
