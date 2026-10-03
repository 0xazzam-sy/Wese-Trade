"""Route groups reserved for later phases.

Each exposes only an honest `/status` endpoint. No market data, signals, scanner rows,
news or backtest results are fabricated here.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.schemas.common import ModuleStatus


def _status_router(module: str, message: str) -> APIRouter:
    router = APIRouter(
        prefix=f"/{module}",
        tags=[module],
        dependencies=[Depends(get_current_user)],
    )

    @router.get("/status", response_model=ModuleStatus)
    async def module_status() -> ModuleStatus:
        return ModuleStatus(module=module, available=False, phase="planned", message=message)

    return router


markets_router = _status_router("markets", "BingX market data provider is not implemented yet.")
signals_router = _status_router("signals", "Signal engine is not implemented yet.")
scanner_router = _status_router("scanner", "Market scanner is not implemented yet.")
backtests_router = _status_router("backtests", "Backtesting engine is not implemented yet.")
