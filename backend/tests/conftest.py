from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Environment, Settings
from app.core.state import AppResources
from app.db.base import Base
from app.main import create_app
from app.models.user import User, UserRole
from app.services.user_service import create_user

TEST_SECRET = "test-secret-key-that-is-long-enough-for-hs256-signing"
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "Correct-Horse-Battery-9"
FRONTEND_ORIGIN = "http://localhost:5173"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        app_env=Environment.TEST,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        secret_key=TEST_SECRET,
        frontend_origin=[FRONTEND_ORIGIN],
        log_level="WARNING",
        ws_heartbeat_seconds=0.2,
        _env_file=None,
    )


@pytest.fixture
async def app(settings: Settings) -> AsyncIterator[FastAPI]:
    application = create_app(settings)
    resources: AppResources = application.state.resources
    async with resources.database.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield application
    await resources.database.dispose()


@pytest.fixture
async def session(app: FastAPI) -> AsyncIterator[AsyncSession]:
    resources: AppResources = app.state.resources
    async with resources.database.session_factory() as db_session:
        yield db_session


@pytest.fixture
async def admin_user(session: AsyncSession) -> User:
    return await create_user(
        session, username=ADMIN_USERNAME, password=ADMIN_PASSWORD, role=UserRole.ADMIN
    )


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
        yield http
