from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import Resources
from app.schemas.health import HealthResponse
from app.services.health_service import get_health

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse)
async def health(resources: Resources) -> HealthResponse:
    return await get_health(resources.settings, resources.database)
