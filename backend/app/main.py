"""FastAPI application factory and lifecycle."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.v1.router import api_router
from app.auth.rate_limit import LoginRateLimiter
from app.core.config import API_V1_PREFIX, BACKEND_DIR, Settings, get_settings
from app.core.logging import configure_logging, get_logger
from app.core.state import AppResources
from app.db.session import Database
from app.websocket.events import CLOSE_SERVER_SHUTDOWN
from app.websocket.manager import ConnectionManager

logger = get_logger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, json_output=settings.is_production)

    resources = AppResources(
        settings=settings,
        database=Database(settings),
        login_limiter=LoginRateLimiter(),
        connections=ConnectionManager(),
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        logger.info(
            "app.starting",
            extra={"fields": {"env": settings.app_env.value, "version": __version__}},
        )
        if settings.uses_placeholder_secret:
            logger.warning("config.placeholder_secret: set a unique SECRET_KEY in backend/.env")
        if await resources.database.ping():
            logger.info("db.connected")
        else:
            logger.error("db.unavailable: check DATABASE_URL and run `alembic upgrade head`")
        yield
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
    app.include_router(api_router, prefix=API_V1_PREFIX)
    return app


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
