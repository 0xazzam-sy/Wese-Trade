from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI

from app.core.state import AppResources


async def test_health_reports_ok(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "NeuralShot"
    assert body["api_version"] == "v1"
    assert body["database"] == {"status": "ok"}
    assert body["timestamp"].endswith("Z")


async def test_database_connectivity(app: FastAPI) -> None:
    resources: AppResources = app.state.resources
    assert await resources.database.ping() is True


async def test_health_degraded_when_database_unavailable(
    app: FastAPI, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    resources: AppResources = app.state.resources

    async def _fail() -> bool:
        return False

    monkeypatch.setattr(resources.database, "ping", _fail)
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["database"]["status"] == "unavailable"
