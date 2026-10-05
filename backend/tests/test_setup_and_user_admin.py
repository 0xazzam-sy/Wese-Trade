"""First-run admin setup and admin user management (no terminal needed)."""

from __future__ import annotations

import httpx

from app.auth.tokens import ACCESS_COOKIE_NAME
from app.models.user import User
from tests.conftest import ADMIN_PASSWORD, ADMIN_USERNAME

STRONG = "Another-Strong-Pass-42"


async def _login(client: httpx.AsyncClient, username: str, password: str) -> httpx.Response:
    return await client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )


async def test_first_run_setup_creates_admin_once(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/v1/auth/setup")).json() == {"needs_setup": True}
    weak = await client.post("/api/v1/auth/setup", json={"username": "owner", "password": "short"})
    assert weak.status_code == 422
    assert weak.json()["detail"] == "weak_password"

    created = await client.post(
        "/api/v1/auth/setup", json={"username": "Owner", "password": STRONG}
    )
    assert created.status_code == 201
    assert created.json()["user"] == {
        **created.json()["user"],
        "username": "owner",
        "role": "admin",
    }
    assert f"{ACCESS_COOKIE_NAME}=" in created.headers["set-cookie"]  # signed in immediately
    assert (await client.get("/api/v1/auth/me")).json()["username"] == "owner"

    assert (await client.get("/api/v1/auth/setup")).json() == {"needs_setup": False}
    again = await client.post("/api/v1/auth/setup", json={"username": "evil", "password": STRONG})
    assert again.status_code == 409
    assert again.json()["detail"] == "setup_complete"


async def test_setup_refused_when_users_exist(client: httpx.AsyncClient, admin_user: User) -> None:
    response = await client.post(
        "/api/v1/auth/setup", json={"username": "x-admin", "password": STRONG}
    )
    assert response.status_code == 409


async def test_admin_manages_users_and_roles(client: httpx.AsyncClient, admin_user: User) -> None:
    assert (await client.get("/api/v1/users")).status_code == 401
    await _login(client, ADMIN_USERNAME, ADMIN_PASSWORD)

    created = await client.post(
        "/api/v1/users", json={"username": "ana", "password": STRONG, "role": "analyst"}
    )
    assert created.status_code == 201
    analyst_id = created.json()["id"]
    dup = await client.post(
        "/api/v1/users", json={"username": "ANA", "password": STRONG, "role": "viewer"}
    )
    assert dup.status_code == 409
    assert dup.json()["detail"] == "username_taken"
    listed = (await client.get("/api/v1/users")).json()["items"]
    assert [u["username"] for u in listed] == [ADMIN_USERNAME, "ana"]
    assert all("password_hash" not in u for u in listed)

    # the last active admin can be neither demoted nor disabled
    last = await client.patch(f"/api/v1/users/{admin_user.id}", json={"role": "viewer"})
    assert last.status_code == 422
    assert last.json()["detail"] == "last_admin"
    assert (
        await client.patch(f"/api/v1/users/{admin_user.id}", json={"is_active": False})
    ).status_code == 422

    changed = await client.patch(f"/api/v1/users/{analyst_id}", json={"role": "viewer"})
    assert changed.json()["role"] == "viewer"
    reset = await client.post(
        f"/api/v1/users/{analyst_id}/password", json={"password": "Brand-New-Pass-77"}
    )
    assert reset.status_code == 204

    other = httpx.AsyncClient(transport=client._transport, base_url="http://testserver")
    async with other:
        assert (await _login(other, "ana", "Brand-New-Pass-77")).status_code == 200
        assert (await other.get("/api/v1/users")).status_code == 403  # viewer: forbidden
        await client.patch(f"/api/v1/users/{analyst_id}", json={"is_active": False})
        # a disabled account loses its existing session immediately
        assert (await other.get("/api/v1/auth/me")).status_code == 401
        assert (await _login(other, "ana", "Brand-New-Pass-77")).status_code == 401
