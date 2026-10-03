"""Async engine/session management.

The engine is created from DATABASE_URL, so switching SQLite -> PostgreSQL requires only
configuration (plus the asyncpg driver), not business-logic changes.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import event, text
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import ConnectionPoolEntry

from app.core.config import Settings


def _enable_sqlite_pragmas(dbapi_connection: DBAPIConnection, _: ConnectionPoolEntry) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


def create_engine(settings: Settings) -> AsyncEngine:
    if (path := settings.sqlite_path) is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    if settings.is_sqlite:
        event.listen(engine.sync_engine, "connect", _enable_sqlite_pragmas)
    return engine


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


class Database:
    """Owns the engine and session factory for the lifetime of the application."""

    def __init__(self, settings: Settings) -> None:
        self.engine = create_engine(settings)
        self.session_factory = create_session_factory(self.engine)

    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self.session_factory() as session:
            yield session

    async def ping(self) -> bool:
        try:
            async with self.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception:
            return False
        return True

    async def dispose(self) -> None:
        await self.engine.dispose()
