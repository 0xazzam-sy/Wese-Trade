from __future__ import annotations

from app import __version__
from app.core.config import API_VERSION, Settings
from app.db.session import Database
from app.schemas.health import DatabaseHealth, HealthResponse
from app.utils.time import utc_now


async def get_health(settings: Settings, database: Database) -> HealthResponse:
    db_ok = await database.ping()
    return HealthResponse(
        status="ok" if db_ok else "degraded",
        service=settings.app_name,
        version=__version__,
        api_version=API_VERSION,
        database=DatabaseHealth(status="ok" if db_ok else "unavailable"),
        timestamp=utc_now(),
    )
