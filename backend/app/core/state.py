"""Typed container for long-lived application resources (stored on `app.state`)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from app.analysis.service import AnalysisService
from app.auth.rate_limit import LoginRateLimiter
from app.core.config import Settings
from app.db.session import Database
from app.execution.service import ExecutionService
from app.forward_test.service import ForwardTestService
from app.market_data.engine import MarketDataEngine
from app.news.service import NewsService
from app.signal_engine.service import SignalService
from app.strategy43.service import Strategy43Service
from app.telegram.service import TelegramService
from app.weather.service import WeatherService
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
    forward_test: ForwardTestService | None = None
    execution: ExecutionService | None = None
    strategy43: Strategy43Service | None = None
    telegram: TelegramService | None = None
    news: NewsService | None = None
    weather: WeatherService | None = None
    # Set by the desktop entrypoint: asks uvicorn to exit gracefully.
    request_shutdown: Callable[[], None] | None = None
