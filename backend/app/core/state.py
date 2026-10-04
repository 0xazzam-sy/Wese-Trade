"""Typed container for long-lived application resources (stored on `app.state`)."""

from __future__ import annotations

from dataclasses import dataclass

from app.analysis.service import AnalysisService
from app.auth.rate_limit import LoginRateLimiter
from app.core.config import Settings
from app.db.session import Database
from app.market_data.engine import MarketDataEngine
from app.signal_engine.service import SignalService
from app.websocket.manager import ConnectionManager


@dataclass(slots=True)
class AppResources:
    settings: Settings
    database: Database
    login_limiter: LoginRateLimiter
    connections: ConnectionManager
    market: MarketDataEngine | None = None
    analysis: AnalysisService | None = None
    signals: SignalService | None = None
