from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from app.core.config import Settings
from app.weather.service import WeatherService, WeatherUnavailableError


def _settings(tmp_path: Path, **kw: object) -> Settings:
    return Settings(secret_key="s" * 40, runtime_root=tmp_path, _env_file=None, **kw)  # type: ignore[arg-type]


async def test_current_weather_maps_real_fields(tmp_path: Path) -> None:
    calls: list[httpx.URL] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url)
        return httpx.Response(
            200,
            json={
                "timezone": "Asia/Riyadh",
                "current": {
                    "time": "2026-10-05T12:00",
                    "temperature_2m": 31.4,
                    "weather_code": 2,
                    "wind_speed_10m": 12.0,
                    "relative_humidity_2m": 20,
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = WeatherService(_settings(tmp_path), client)
        first = await service.current(24.7136, 46.6753)
        second = await service.current(24.7139, 46.6751)  # same ~1 km cell: cached
    assert first == second
    assert len(calls) == 1
    assert calls[0].params["latitude"] == "24.71"
    assert first["temperature_c"] == 31.4
    assert first["condition_ar"] == "غائم جزئياً"
    assert first["source"] == "Open-Meteo"


async def test_failures_never_invent_values(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"current": {}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = WeatherService(_settings(tmp_path), client)
        with pytest.raises(WeatherUnavailableError):
            await service.current(1.0, 2.0)

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(down)) as client:
        with pytest.raises(WeatherUnavailableError):
            await WeatherService(_settings(tmp_path), client).search("الرياض")
    with pytest.raises(WeatherUnavailableError, match="disabled"):
        await WeatherService(_settings(tmp_path, weather_enabled=False)).current(1, 2)


async def test_weather_api_requires_login_and_reports_unavailable(
    client: httpx.AsyncClient, admin_user: object
) -> None:
    assert (
        await client.get("/api/v1/weather/current", params={"lat": 1, "lon": 2})
    ).status_code == 401
    from tests.conftest import ADMIN_PASSWORD, ADMIN_USERNAME

    await client.post(
        "/api/v1/auth/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD}
    )
    response = await client.get("/api/v1/weather/current", params={"lat": 1, "lon": 2})
    assert response.status_code == 503  # disabled in tests: an honest "unavailable"
    assert (
        await client.get("/api/v1/weather/current", params={"lat": 100, "lon": 2})
    ).status_code == 422
