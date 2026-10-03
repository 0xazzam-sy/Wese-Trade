from __future__ import annotations

import asyncio
import io
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.config import Settings, get_settings
from app.db.base import Base
from app.db.session import Database
from app.models.user import User, UserRole
from app.scripts import create_admin
from tests.conftest import TEST_SECRET


@pytest.fixture
def isolated_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Settings]:
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'admin.db'}")
    monkeypatch.setenv("SECRET_KEY", TEST_SECRET)
    get_settings.cache_clear()
    settings = get_settings()
    yield settings
    get_settings.cache_clear()


async def _prepare_schema(settings: Settings) -> None:
    database = Database(settings)
    async with database.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await database.dispose()


async def _users(settings: Settings) -> list[User]:
    database = Database(settings)
    async with database.session_factory() as session:
        users = list((await session.scalars(select(User))).all())
    await database.dispose()
    return users


def test_create_admin_bootstrap_and_refuse_second_run(
    isolated_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    asyncio.run(_prepare_schema(isolated_settings))

    monkeypatch.setattr("sys.stdin", io.StringIO("Bootstrap-Admin-Pass1\n"))
    assert create_admin.main(["--username", "Root", "--password-stdin"]) == 0
    users = asyncio.run(_users(isolated_settings))
    assert [(u.username, u.role) for u in users] == [("root", UserRole.ADMIN)]

    monkeypatch.setattr("sys.stdin", io.StringIO("Another-Admin-Pass2\n"))
    assert create_admin.main(["--username", "second", "--password-stdin"]) == 1

    monkeypatch.setattr("sys.stdin", io.StringIO("Another-Admin-Pass2\n"))
    assert create_admin.main(["--username", "second", "--password-stdin", "--additional"]) == 0


def test_create_admin_rejects_weak_password(
    isolated_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    asyncio.run(_prepare_schema(isolated_settings))
    monkeypatch.setattr("sys.stdin", io.StringIO("short\n"))
    assert create_admin.main(["--username", "root", "--password-stdin"]) == 1


def test_create_admin_requires_migrated_database(
    isolated_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("Bootstrap-Admin-Pass1\n"))
    assert create_admin.main(["--username", "root", "--password-stdin"]) == 2
