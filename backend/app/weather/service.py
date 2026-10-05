"""Current weather via Open-Meteo (free, no API key), proxied by the backend.

The browser/desktop UI only ever talks to the local backend (CSP: no third-party
connections from the frontend). Values are real or absent: on any failure the API returns
``weather_unavailable`` and the UI says so; temperatures are never invented.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import Settings
from app.core.logging import get_logger

logger = get_logger(__name__)
CACHE_SECONDS = 600

# WMO weather interpretation codes (Open-Meteo docs) -> Arabic.
WMO_AR: dict[int, str] = {
    0: "صافٍ",
    1: "صافٍ غالباً",
    2: "غائم جزئياً",
    3: "غائم",
    45: "ضباب",
    48: "ضباب متجمد",
    51: "رذاذ خفيف",
    53: "رذاذ",
    55: "رذاذ كثيف",
    56: "رذاذ متجمد",
    57: "رذاذ متجمد كثيف",
    61: "مطر خفيف",
    63: "مطر",
    65: "مطر غزير",
    66: "مطر متجمد",
    67: "مطر متجمد غزير",
    71: "ثلج خفيف",
    73: "ثلج",
    75: "ثلج كثيف",
    77: "حبيبات ثلجية",
    80: "زخات مطر خفيفة",
    81: "زخات مطر",
    82: "زخات مطر عنيفة",
    85: "زخات ثلج",
    86: "زخات ثلج كثيفة",
    95: "عاصفة رعدية",
    96: "عاصفة رعدية مع برد",
    99: "عاصفة رعدية شديدة مع برد",
}


class WeatherUnavailableError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Place:
    name: str
    country: str | None
    latitude: float
    longitude: float
    timezone: str | None


class WeatherService:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self._client = client
        self._cache: dict[tuple[float, float], tuple[float, dict[str, Any]]] = {}

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(8.0))
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _get(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self.settings.weather_enabled:
            raise WeatherUnavailableError("weather_disabled")
        try:
            response = await self._http().get(url, params=params)
            response.raise_for_status()
            payload: dict[str, Any] = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("weather.request_failed", extra={"fields": {"error": str(exc)}})
            raise WeatherUnavailableError("weather_unavailable") from exc
        return payload

    async def search(self, query: str) -> list[Place]:
        payload = await self._get(
            self.settings.weather_geocoding_url,
            {"name": query, "count": 5, "language": "ar", "format": "json"},
        )
        return [
            Place(
                name=str(r["name"]),
                country=r.get("country"),
                latitude=float(r["latitude"]),
                longitude=float(r["longitude"]),
                timezone=r.get("timezone"),
            )
            for r in payload.get("results") or []
        ]

    async def current(self, latitude: float, longitude: float) -> dict[str, Any]:
        key = (round(latitude, 2), round(longitude, 2))
        cached = self._cache.get(key)
        now = time.monotonic()
        if cached and now - cached[0] < CACHE_SECONDS:
            return cached[1]
        payload = await self._get(
            self.settings.weather_api_url,
            {
                "latitude": key[0],
                "longitude": key[1],
                "current": "temperature_2m,weather_code,wind_speed_10m,relative_humidity_2m",
                "timezone": "auto",
            },
        )
        current = payload.get("current") or {}
        if "temperature_2m" not in current:
            raise WeatherUnavailableError("weather_unavailable")
        code = int(current.get("weather_code", -1))
        result = {
            "temperature_c": float(current["temperature_2m"]),
            "weather_code": code,
            "condition_ar": WMO_AR.get(code, "غير معروف"),
            "wind_kmh": current.get("wind_speed_10m"),
            "humidity": current.get("relative_humidity_2m"),
            "observed_at": current.get("time"),
            "timezone": payload.get("timezone"),
            "source": "Open-Meteo",
        }
        self._cache[key] = (now, result)
        return result
