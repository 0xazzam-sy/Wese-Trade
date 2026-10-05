"""FastAPI application factory and lifecycle."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app import __version__
from app.analysis.service import AnalysisService
from app.api.v1.router import api_router
from app.auth.rate_limit import LoginRateLimiter
from app.core.config import API_V1_PREFIX, Settings, get_settings
from app.core.logging import configure_logging, get_logger
from app.core.runtime import BACKEND_DIR
from app.core.state import AppResources
from app.db.session import Database
from app.forward_test.bootstrap import ensure_run, okx_active_symbols
from app.forward_test.service import ForwardTestService
from app.market_data.factory import build_market_engine
from app.news.service import NewsService
from app.signal_engine.service import SignalService
from app.weather.service import WeatherService
from app.web import mount_web
from app.websocket.events import CLOSE_SERVER_SHUTDOWN
from app.websocket.manager import ConnectionManager

logger = get_logger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    if not settings.is_desktop:  # the desktop entrypoint configures file logging itself
        configure_logging(settings.log_level, json_output=settings.is_production)

    connections = ConnectionManager()
    market = build_market_engine(settings, connections) if settings.market_data_enabled else None
    database = Database(settings)
    analysis = (
        AnalysisService(market, include_debug=not settings.is_production)
        if market is not None
        else None
    )
    signals = (
        SignalService(analysis, market, database)
        if analysis is not None and market is not None
        else None
    )
    forward_test = (
        ForwardTestService(analysis, market, database)
        if analysis is not None and market is not None
        else None
    )
    if signals is not None and forward_test is not None:
        signals.excluded = forward_test.owns
        signals.delegate = forward_test
    news = NewsService(settings, cache_file=settings.paths.cache / "news.json")
    weather = WeatherService(settings)
    resources = AppResources(
        settings=settings,
        database=database,
        login_limiter=LoginRateLimiter(),
        connections=connections,
        market=market,
        analysis=analysis,
        signals=signals,
        forward_test=forward_test,
        news=news,
        weather=weather,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        logger.info(
            "app.starting",
            extra={"fields": {"env": settings.app_env.value, "version": __version__}},
        )
        if settings.uses_placeholder_secret:
            logger.warning(
                "config.placeholder_secret: SECRET_KEY is the placeholder. Generate one with "
                '`python -c "import secrets; print(secrets.token_urlsafe(64))"` and set '
                "SECRET_KEY in backend/.env (refused when APP_ENV=production)"
            )
        if await resources.database.ping():
            logger.info("db.connected")
        else:
            logger.error("db.unavailable: check DATABASE_URL and run `alembic upgrade head`")
        if settings.is_desktop and resources.forward_test is not None:
            await _ensure_desktop_run(settings, resources.database)
        if resources.market is not None:
            # Starts in the background: an exchange outage never blocks or crashes startup.
            await resources.market.start()
        if resources.analysis is not None:
            await resources.analysis.start()
        if resources.signals is not None:
            await resources.signals.start()
        if resources.forward_test is not None:
            await resources.forward_test.start()
        await news.start()
        yield
        await news.stop()
        await weather.close()
        if resources.forward_test is not None:
            await resources.forward_test.stop()
        if resources.signals is not None:
            await resources.signals.stop()
        if resources.analysis is not None:
            await resources.analysis.stop()
        if resources.market is not None:
            await resources.market.stop()
        await resources.connections.close_all(CLOSE_SERVER_SHUTDOWN, "server_shutdown")
        await resources.database.dispose()
        logger.info("app.stopped")

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        lifespan=lifespan,
        docs_url=None if settings.is_production else "/api/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/api/openapi.json",
    )
    app.state.resources = resources

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.frontend_origin,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Accept"],
    )
    if settings.is_desktop:
        # Loopback names only: defeats DNS-rebinding against the local service.
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])
    app.include_router(api_router, prefix=API_V1_PREFIX)
    if settings.web_dir is not None:
        mount_web(app, settings.web_dir, desktop=settings.is_desktop)
    return app


async def _ensure_desktop_run(settings: Settings, database: Database) -> None:
    """Desktop: resume the local open run, or start a NEW one now (never backdated)."""

    async def active() -> set[str]:
        return await asyncio.wait_for(okx_active_symbols(settings.okx_rest_url), timeout=8)

    try:
        await ensure_run(
            database, notes="desktop installation run (Phase 4.3)", active_symbols=active
        )
    except Exception:
        logger.exception("forward_test.bootstrap_failed")


def run() -> None:
    """Entry point for `python -m app.main`."""
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:create_app",
        factory=True,
        host=settings.app_host,
        port=settings.app_port,
        reload=not settings.is_production,
        reload_dirs=[str(BACKEND_DIR / "app")],
        log_config=None,
    )


if __name__ == "__main__":
    run()
