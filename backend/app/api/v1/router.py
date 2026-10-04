from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.endpoints import analysis, auth, health, markets, news
from app.api.v1.endpoints.placeholders import (
    backtests_router,
    scanner_router,
    signals_router,
)
from app.websocket.routes import router as ws_router

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(news.router)
api_router.include_router(markets.router)
api_router.include_router(analysis.router)
api_router.include_router(signals_router)
api_router.include_router(scanner_router)
api_router.include_router(backtests_router)
api_router.include_router(ws_router)
