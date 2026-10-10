"""Strategy 4.3 routes (v1.2): engine health, market-wide scanner, stream state, history.

Read-only. Wese Trade never places trades; the user executes manually.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import Resources, get_current_user
from app.market_data.timeframes import Timeframe
from app.strategy43 import store
from app.strategy43.config import TIMEFRAMES
from app.strategy43.service import Strategy43Service

router = APIRouter(
    prefix="/strategy43", tags=["strategy-4.3"], dependencies=[Depends(get_current_user)]
)


def _service(resources: Resources) -> Strategy43Service:
    if resources.strategy43 is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="market_data_disabled")
    return resources.strategy43


Service = Annotated[Strategy43Service, Depends(_service)]


@router.get("/health")
async def engine_health(service: Service, resources: Resources) -> dict[str, Any]:
    """Production health: «محرك الإشارات» with the real technical problem when degraded."""
    out = service.health()
    try:
        out["signals"] = await service.counts()
    except Exception as exc:  # health must answer even when the database is unhappy
        out["signals"] = {}
        out["problems"] = [*out["problems"], f"تعذر قراءة عدد الإشارات: {exc!r}"[:200]]
    if resources.execution is not None:
        ex = resources.execution.health()
        out["execution"] = {
            "version": ex["version"],
            "streams": len(ex["streams"]),
            "confirmed": ex["confirmed"],
            "parent_source": ex["parent_source"],
        }
    telegram = resources.telegram
    out["telegram"] = await telegram.health() if telegram is not None else None
    forward = resources.forward_test
    out["baseline_4_2"] = (
        {k: forward.health()[k] for k in ("state", "version", "fingerprint", "status")}
        if forward is not None
        else None
    )
    return out


@router.get("/opportunities")
async def opportunities(service: Service, limit: int = Query(20, ge=1, le=100)) -> dict[str, Any]:
    """«أفضل الفرص الآن»: open confirmed opportunities across the scanned market."""
    items = service.opportunities(limit)
    health = service.health()
    return {
        "items": items,
        "universe_size": health["universe_size"],
        "markets_scanned": health["markets_scanned"],
        "symbols_with_opportunity": health["symbols_with_opportunity"],
        "last_scan_at": health["last_scan_at"],
        "state": health["state"],
    }


@router.get("/chart-signals")
async def chart_signals(
    service: Service,
    symbol: str,
    timeframe: Timeframe,
    limit: int = Query(200, ge=1, le=500),
) -> dict[str, Any]:
    """Persisted confirmed 4.3 signals of one chart stream (markers survive restarts)."""
    capable = timeframe.value in TIMEFRAMES
    items: list[dict[str, Any]] = []
    if capable and service.database is not None:
        async with service.database.session_factory() as session:
            rows = await store.recent_signals(session, symbol.upper(), timeframe.value, limit)
        items = [service.signal_view(s) for s in rows]
    return {
        "symbol": symbol.upper(),
        "timeframe": timeframe.value,
        "signal_capable": capable,
        "strategy_version": service.version,
        "fingerprint": service.fingerprint,
        "items": items,
    }


@router.get("/{symbol}")
async def stream_state(symbol: str, timeframe: Timeframe, service: Service) -> dict[str, Any]:
    if timeframe.value not in TIMEFRAMES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="not_a_primary_timeframe")
    return service.state((symbol.upper(), timeframe))


@router.get("/{symbol}/history")
async def history(
    symbol: str,
    service: Service,
    timeframe: Timeframe | None = None,
    limit: int = Query(50, ge=1, le=500),
) -> list[dict[str, Any]]:
    if service.database is None:
        return []
    async with service.database.session_factory() as session:
        rows = await store.recent_signals(
            session, symbol.upper(), timeframe.value if timeframe else None, limit
        )
    return [service.signal_view(s) for s in rows]
