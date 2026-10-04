"""Signal routes (Phase 4). Signals are analytical, never trading instructions; scores are
/100 confluence values, never probabilities. There are no order/execution endpoints."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import Resources, SessionDep, get_current_user, require_roles
from app.api.v1.endpoints.markets import _translate
from app.market_data.exceptions import MarketDataError
from app.market_data.timeframes import Timeframe
from app.models.user import UserRole
from app.services import signal_store
from app.signal_engine.service import SignalService

router = APIRouter(prefix="/signals", tags=["signals"], dependencies=[Depends(get_current_user)])
backtests_router = APIRouter(
    prefix="/backtests",
    tags=["backtests"],
    dependencies=[Depends(require_roles(UserRole.ADMIN, UserRole.ANALYST))],
)


def _service(resources: Resources) -> SignalService:
    if resources.signals is None or resources.market is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="market_data_disabled")
    if not resources.market.symbols.loaded:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="market_data_loading")
    return resources.signals


Service = Annotated[SignalService, Depends(_service)]


@router.get("/health")
async def signals_health(service: Service) -> dict[str, Any]:
    return service.health()


@router.get("/{symbol}")
async def get_signal(symbol: str, timeframe: Timeframe, service: Service) -> dict[str, Any]:
    """Current evaluation (with component scores, reasons, trade plan), developing
    evaluation, active signal and last confirmed signal for one stream."""
    try:
        market = service.market.symbols.require_active(symbol)
        return await service.current((market.symbol, timeframe))
    except MarketDataError as exc:
        raise _translate(exc) from exc


@router.get("/{symbol}/history")
async def signal_history(
    symbol: str,
    session: SessionDep,
    timeframe: Timeframe | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict[str, Any]:
    items = await signal_store.list_signals(
        session, symbol.strip().upper(), timeframe.value if timeframe else None, limit
    )
    return {"symbol": symbol.strip().upper(), "items": items}


@backtests_router.get("")
async def list_backtests(session: SessionDep) -> dict[str, Any]:
    return {"items": await signal_store.list_backtest_runs(session)}


@backtests_router.get("/{run_id}")
async def get_backtest(run_id: int, session: SessionDep) -> dict[str, Any]:
    run = await signal_store.get_backtest_run(session, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="backtest_not_found")
    return run
