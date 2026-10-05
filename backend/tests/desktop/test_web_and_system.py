"""Same-origin web serving, CSP, runtime info, desktop shutdown hook, run bootstrap."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from app.core.config import Environment, Settings
from app.core.runtime import RuntimeMode
from app.db.base import Base
from app.db.session import Database
from app.forward_test import store
from app.forward_test.bootstrap import ensure_run
from app.forward_test.candidate import UNIVERSE
from app.main import create_app
from tests.conftest import ADMIN_PASSWORD, ADMIN_USERNAME, TEST_SECRET


def _web(tmp_path: Path) -> Path:
    web = tmp_path / "web"
    (web / "assets").mkdir(parents=True)
    (web / "index.html").write_text("<!doctype html><title>Wese Trade</title>", encoding="utf-8")
    (web / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    return web


def _desktop_settings(tmp_path: Path, **kw: object) -> Settings:
    return Settings(
        app_env=Environment.PRODUCTION,
        runtime_mode=RuntimeMode.DESKTOP,
        runtime_root=tmp_path / "root",
        secret_key=TEST_SECRET,
        market_data_enabled=False,
        news_enabled=False,
        weather_enabled=False,
        log_level="WARNING",
        _env_file=None,
        **kw,  # type: ignore[arg-type]
    )


async def _client(settings: Settings) -> tuple[httpx.AsyncClient, object]:
    app = create_app(settings)
    async with app.state.resources.database.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    http = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:47123"
    )
    return http, app


async def test_spa_is_served_same_origin_with_csp(tmp_path: Path) -> None:
    http, app = await _client(_desktop_settings(tmp_path, web_dir=_web(tmp_path)))
    async with http:
        index = await http.get("/")
        assert index.status_code == 200 and "Wese Trade" in index.text
        csp = index.headers["content-security-policy"]
        assert "default-src 'self'" in csp and "script-src 'self'" in csp
        assert "connect-src 'self' ws://127.0.0.1:47123 http://127.0.0.1:47123" in csp
        assert "okx" not in csp  # the UI never talks to OKX directly
        assert index.headers["cache-control"] == "no-store"
        # client-side routes fall back to the SPA; real assets and API are untouched
        assert "Wese Trade" in (await http.get("/forward-test")).text
        assert (await http.get("/assets/app.js")).text == "console.log(1)"
        assert (await http.get("/assets/missing.js")).status_code == 404
        health = await http.get("/api/v1/health")
        assert health.json()["status"] == "ok"
        assert "content-security-policy" not in health.headers
        assert (await http.get("/api/v1/nope")).status_code == 404
    await app.state.resources.database.dispose()  # type: ignore[attr-defined]


async def test_shutdown_hook_requires_desktop_and_token(tmp_path: Path) -> None:
    calls: list[int] = []
    http, app = await _client(_desktop_settings(tmp_path, desktop_token="t" * 32))
    app.state.resources.request_shutdown = lambda: calls.append(1)  # type: ignore[attr-defined]
    async with http:
        url = "/api/v1/system/shutdown"
        assert (await http.post(url)).status_code == 404
        assert (await http.post(url, headers={"X-Wese-Desktop-Token": "wrong"})).status_code == 404
        ok = await http.post(url, headers={"X-Wese-Desktop-Token": "t" * 32})
        assert ok.status_code == 202 and calls == [1]
    await app.state.resources.database.dispose()  # type: ignore[attr-defined]


async def test_shutdown_hook_absent_in_development(
    client: httpx.AsyncClient, settings: Settings
) -> None:
    response = await client.post(
        "/api/v1/system/shutdown", headers={"X-Wese-Desktop-Token": "anything"}
    )
    assert response.status_code == 404


async def test_runtime_info(client: httpx.AsyncClient, admin_user: object) -> None:
    assert (await client.get("/api/v1/system/runtime")).status_code == 401
    await client.post(
        "/api/v1/auth/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD}
    )
    body = (await client.get("/api/v1/system/runtime")).json()
    assert body["mode"] == "development"
    assert body["market_provider"] == "OKX"
    assert "paths" not in body  # only shown on desktop


async def test_ensure_run_creates_once_then_resumes(tmp_path: Path) -> None:
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'db.sqlite'}",
        secret_key=TEST_SECRET,
        _env_file=None,
    )
    database = Database(settings)
    async with database.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def offline() -> set[str]:
        raise OSError("no network")

    before = datetime.now(UTC).replace(microsecond=0)
    run, created = await ensure_run(database, notes="desktop", active_symbols=offline)
    assert created
    assert run.strategy_version == "wese-trade-forward-4.2-a03e20f1d4"
    assert run.started_at >= before  # never backdated
    assert run.symbols == list(UNIVERSE)  # offline: pre-registered universe kept
    assert "instrument check unavailable" in run.notes

    again, created_again = await ensure_run(database, notes="desktop", active_symbols=offline)
    assert not created_again and again.id == run.id and again.started_at == run.started_at
    async with database.session_factory() as session:
        assert len(await store.signal_rows(session, run.id, limit=None)) == 0
    await database.dispose()


async def test_ensure_run_excludes_inactive_symbols(tmp_path: Path) -> None:
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'db.sqlite'}",
        secret_key=TEST_SECRET,
        _env_file=None,
    )
    database = Database(settings)
    async with database.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def live() -> set[str]:
        return set(UNIVERSE) - {"PUMPUSDT"}

    run, _ = await ensure_run(database, notes="n", active_symbols=live)
    assert "PUMPUSDT" not in run.symbols and "PUMPUSDT" in run.notes
    await database.dispose()


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.5"])  # noqa: S104
def test_desktop_never_binds_beyond_loopback(tmp_path: Path, host: str) -> None:
    with pytest.raises(ValueError, match="loopback"):
        _desktop_settings(tmp_path, app_host=host)
