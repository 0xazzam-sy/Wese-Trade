"""Weather routes (display only; never coupled to signals)."""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import Resources, get_current_user
from app.weather.service import WeatherService, WeatherUnavailableError

router = APIRouter(prefix="/weather", tags=["weather"], dependencies=[Depends(get_current_user)])


def _service(resources: Resources) -> WeatherService:
    if resources.weather is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "weather_unavailable")
    return resources.weather


Service = Annotated[WeatherService, Depends(_service)]


@router.get("/places")
async def places(
    service: Service, q: Annotated[str, Query(min_length=2, max_length=80)]
) -> dict[str, Any]:
    try:
        return {"items": [asdict(p) for p in await service.search(q)]}
    except WeatherUnavailableError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc


@router.get("/current")
async def current(
    service: Service,
    lat: Annotated[float, Query(ge=-90, le=90)],
    lon: Annotated[float, Query(ge=-180, le=180)],
) -> dict[str, Any]:
    try:
        return await service.current(lat, lon)
    except WeatherUnavailableError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
