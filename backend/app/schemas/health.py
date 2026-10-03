from __future__ import annotations

from datetime import datetime
from typing import Literal

from app.schemas.common import ApiModel


class DatabaseHealth(ApiModel):
    status: Literal["ok", "unavailable"]


class HealthResponse(ApiModel):
    status: Literal["ok", "degraded"]
    service: str
    version: str
    api_version: str
    database: DatabaseHealth
    timestamp: datetime
