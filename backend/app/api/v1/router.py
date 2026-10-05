from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.endpoints import (
    analysis,
    auth,
    forward_test,
    health,
    markets,
    news,
    signals,
    system,
    users,
    weather,
)
from app.websocket.routes import router as ws_router

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(news.router)
api_router.include_router(markets.router)
api_router.include_router(analysis.router)
api_router.include_router(signals.router)
api_router.include_router(forward_test.router)
api_router.include_router(users.router)
api_router.include_router(weather.router)
api_router.include_router(system.router)
api_router.include_router(signals.backtests_router)
api_router.include_router(ws_router)
