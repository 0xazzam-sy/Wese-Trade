from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from tests.conftest import ADMIN_PASSWORD, ADMIN_USERNAME, FRONTEND_ORIGIN

WS_PATH = "/api/v1/ws"


def _logged_in_client(app: FastAPI) -> TestClient:
    client = TestClient(app)
    response = client.post(
        "/api/v1/auth/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD}
    )
    assert response.status_code == 200
    return client


@pytest.mark.usefixtures("admin_user")
def test_ws_lifecycle_status_ping_and_heartbeat(app: FastAPI) -> None:
    with (
        _logged_in_client(app) as client,
        client.websocket_connect(WS_PATH, headers={"origin": FRONTEND_ORIGIN}) as ws,
    ):
        status = ws.receive_json()
        assert status["type"] == "system.status"
        assert status["data"]["state"] == "connected"
        assert status["timestamp"]

        ws.send_json({"type": "system.ping", "data": {"n": 1}})
        # Heartbeats (every 0.2s in tests) may interleave with the pong.
        seen: dict[str, dict[str, object]] = {}
        while not {"system.pong", "system.heartbeat"} <= seen.keys():
            message = ws.receive_json()
            seen[message["type"]] = message
        assert seen["system.pong"]["data"] == {"echo": {"n": 1}}


@pytest.mark.usefixtures("admin_user")
def test_ws_rejects_invalid_messages(app: FastAPI) -> None:
    with (
        _logged_in_client(app) as client,
        client.websocket_connect(WS_PATH, headers={"origin": FRONTEND_ORIGIN}) as ws,
    ):
        ws.receive_json()  # system.status
        ws.send_text("not json")
        received = ws.receive_json()
        while received["type"] == "system.heartbeat":
            received = ws.receive_json()
        assert received["type"] == "system.error"
        assert received["data"]["code"] == "invalid_message"


def test_ws_rejects_unauthenticated(app: FastAPI) -> None:
    with (
        TestClient(app) as client,
        client.websocket_connect(WS_PATH, headers={"origin": FRONTEND_ORIGIN}) as ws,
        pytest.raises(WebSocketDisconnect) as exc_info,
    ):
        ws.receive_json()
    assert exc_info.value.code == 4401


@pytest.mark.usefixtures("admin_user")
def test_ws_rejects_foreign_origin(app: FastAPI) -> None:
    with (
        _logged_in_client(app) as client,
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect(WS_PATH, headers={"origin": "https://evil.example"}),
    ):
        pass
