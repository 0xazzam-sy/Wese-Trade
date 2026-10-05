from __future__ import annotations

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.tokens import ACCESS_COOKIE_NAME, create_access_token
from app.models.user import User
from tests.conftest import ADMIN_PASSWORD, ADMIN_USERNAME, TEST_SECRET


async def _login(client: httpx.AsyncClient, password: str = ADMIN_PASSWORD) -> httpx.Response:
    return await client.post(
        "/api/v1/auth/login", json={"username": ADMIN_USERNAME, "password": password}
    )


async def test_successful_login_sets_httponly_cookie(
    client: httpx.AsyncClient, admin_user: User
) -> None:
    response = await _login(client)
    assert response.status_code == 200
    body = response.json()
    assert body["user"]["username"] == ADMIN_USERNAME
    assert body["user"]["role"] == "admin"
    assert "password_hash" not in body["user"]
    assert "token" not in body  # token is never exposed to JavaScript

    set_cookie = response.headers["set-cookie"]
    assert f"{ACCESS_COOKIE_NAME}=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "SameSite=strict" in set_cookie
    assert "Path=/api/v1" in set_cookie


async def test_failed_login_returns_generic_401(
    client: httpx.AsyncClient, admin_user: User
) -> None:
    wrong_password = await _login(client, password="not-the-right-password")
    unknown_user = await client.post(
        "/api/v1/auth/login", json={"username": "ghost", "password": "whatever-password"}
    )
    assert wrong_password.status_code == 401
    assert unknown_user.status_code == 401
    assert wrong_password.json() == unknown_user.json() == {"detail": "invalid_credentials"}
    assert "set-cookie" not in wrong_password.headers


async def test_login_validation_error(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/v1/auth/login", json={"username": ""})
    assert response.status_code == 422


async def test_login_is_throttled_after_repeated_failures(
    client: httpx.AsyncClient, admin_user: User
) -> None:
    for _ in range(5):
        assert (await _login(client, password="bad-password-attempt")).status_code == 401
    throttled = await _login(client)
    assert throttled.status_code == 429
    assert int(throttled.headers["retry-after"]) > 0


async def test_me_requires_authentication(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401


async def test_me_returns_current_user_after_login(
    client: httpx.AsyncClient, admin_user: User
) -> None:
    await _login(client)
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 200
    assert response.json()["username"] == ADMIN_USERNAME
    assert response.json()["last_login_at"] is not None


async def test_tampered_and_foreign_tokens_rejected(
    client: httpx.AsyncClient, admin_user: User
) -> None:
    foreign = create_access_token(
        user_id=admin_user.id,
        secret_key="another-secret-key-of-sufficient-length!",
        expire_minutes=5,
    )
    client.cookies.set(ACCESS_COOKIE_NAME, foreign.token, path="/api/v1")
    assert (await client.get("/api/v1/auth/me")).status_code == 401

    client.cookies.set(ACCESS_COOKIE_NAME, "garbage.token.value", path="/api/v1")
    assert (await client.get("/api/v1/auth/me")).status_code == 401


async def test_token_for_deactivated_user_rejected(
    client: httpx.AsyncClient, admin_user: User, session: AsyncSession
) -> None:
    token = create_access_token(user_id=admin_user.id, secret_key=TEST_SECRET, expire_minutes=5)
    admin_user.is_active = False
    await session.commit()
    client.cookies.set(ACCESS_COOKIE_NAME, token.token, path="/api/v1")
    assert (await client.get("/api/v1/auth/me")).status_code == 401


async def test_logout_clears_cookie(client: httpx.AsyncClient, admin_user: User) -> None:
    await _login(client)
    response = await client.post("/api/v1/auth/logout")
    assert response.status_code == 204
    assert f'{ACCESS_COOKIE_NAME}=""' in response.headers["set-cookie"]
    assert (await client.get("/api/v1/auth/me")).status_code == 401


async def test_route_groups_are_protected_and_honest(
    client: httpx.AsyncClient, admin_user: User
) -> None:
    assert (await client.get("/api/v1/markets/status")).status_code == 401
    # The scanner is not built yet, so it has no route at all (no placeholder endpoint).
    assert (await client.get("/api/v1/scanner/status")).status_code == 404
    assert (
        await client.get("/api/v1/signals/BTCUSDT", params={"timeframe": "5m"})
    ).status_code == 401
    assert (await client.get("/api/v1/backtests")).status_code == 401
    assert (await client.get("/api/v1/markets/symbols")).status_code == 401
    assert (await client.get("/api/v1/news")).status_code == 401

    await _login(client)
    # Market data disabled in this test config -> honest 503, never fake data.
    assert (await client.get("/api/v1/markets/symbols")).json() == {
        "detail": "market_data_disabled"
    }
    signal = await client.get("/api/v1/signals/BTCUSDT", params={"timeframe": "5m"})
    assert signal.json() == {"detail": "market_data_disabled"}  # honest, never fabricated
    assert (await client.get("/api/v1/backtests")).json() == {"items": []}

    news = (await client.get("/api/v1/news")).json()
    assert news["items"] == []
    assert news["available"] is False


async def test_no_order_or_trading_endpoints_exist(client: httpx.AsyncClient) -> None:
    spec = (await client.get("/api/openapi.json")).json()
    paths = " ".join(spec["paths"].keys()).lower()
    for forbidden in ("order", "trade", "position", "withdraw"):
        assert forbidden not in paths


async def test_session_endpoint_reports_state_without_error(
    client: httpx.AsyncClient, admin_user: User
) -> None:
    anonymous = await client.get("/api/v1/auth/session")
    assert anonymous.status_code == 200
    assert anonymous.json() == {"authenticated": False, "user": None}

    await _login(client)
    authenticated = (await client.get("/api/v1/auth/session")).json()
    assert authenticated["authenticated"] is True
    assert authenticated["user"]["username"] == ADMIN_USERNAME
