"""Real sidecar process lifecycle: start, health, graceful stop, parent-death, persistence.

The sidecar runs with OKX pointed at a closed local port (offline simulation), so these
tests never touch the network and also prove that offline startup works.
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

BACKEND = Path(__file__).resolve().parents[2]
TOKEN = "desktop-test-token-0123456789abcdef"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class Sidecar:
    def __init__(self, root: Path, port: int) -> None:
        self.root, self.port = root, port
        root.parent.mkdir(parents=True, exist_ok=True)
        env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", str(root)),
            "PYTHONPATH": str(BACKEND),
            "WESE_RUNTIME_ROOT": str(root),
            "WESE_PORT": str(port),
            "WESE_DESKTOP_TOKEN": TOKEN,
            "WESE_STDIN_WATCHDOG": "1",
            "OKX_REST_URL": "http://127.0.0.1:9",
            "OKX_PUBLIC_WS_URL": "ws://127.0.0.1:9",
            "OKX_BUSINESS_WS_URL": "ws://127.0.0.1:9",
            "NEWS_ENABLED": "false",
            "WEATHER_ENABLED": "false",
        }
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "app.desktop"],
            cwd=str(root.parent),  # never depends on the working directory
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        self.url = f"http://127.0.0.1:{port}"

    def wait_ready(self, timeout: float = 45) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise AssertionError(self.proc.stderr.read().decode() if self.proc.stderr else "")
            try:
                if httpx.get(f"{self.url}/api/v1/health", timeout=1).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.2)
        raise AssertionError("sidecar did not become healthy")

    def wait_exit(self, timeout: float = 20) -> int:
        return self.proc.wait(timeout=timeout)

    def kill(self) -> None:
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait(5)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "مستخدم تجريبي" / "Wese Trade"


@pytest.fixture
def sidecar(root: Path) -> Iterator[Sidecar]:
    car = Sidecar(root, _free_port())
    yield car
    car.kill()


def _shutdown(car: Sidecar) -> int:
    response = httpx.post(
        f"{car.url}/api/v1/system/shutdown", headers={"X-Wese-Desktop-Token": TOKEN}
    )
    assert response.status_code == 202
    return car.wait_exit()


def test_start_health_setup_shutdown_and_persistence(sidecar: Sidecar, root: Path) -> None:
    sidecar.wait_ready()
    with httpx.Client(base_url=sidecar.url) as http:
        assert http.get("/api/v1/auth/setup").json() == {"needs_setup": True}
        made = http.post(
            "/api/v1/auth/setup", json={"username": "owner", "password": "Owner-Strong-Pass-1"}
        )
        assert made.status_code == 201
        runtime = http.get("/api/v1/system/runtime").json()
        assert runtime["mode"] == "desktop"
        assert runtime["strategy"]["version"] == "wese-trade-forward-4.2-a03e20f1d4"
        assert runtime["paths"]["data"] == str((root / "data").resolve())
        status = http.get("/api/v1/forward-test/status").json()
        first_run = status["run"]
        assert first_run["status"] == "forward_testing"
    assert _shutdown(sidecar) == 0
    assert (root / "logs" / "backend.log").exists()
    assert (root / "logs" / "forward-test.log").exists()

    # reopen: same DB, same user, same run, no duplicate run
    again = Sidecar(root, _free_port())
    try:
        again.wait_ready()
        with httpx.Client(base_url=again.url) as http:
            assert http.get("/api/v1/auth/setup").json() == {"needs_setup": False}
            login = http.post(
                "/api/v1/auth/login",
                json={"username": "owner", "password": "Owner-Strong-Pass-1"},
            )
            assert login.status_code == 200
            assert http.get("/api/v1/forward-test/status").json()["run"] == first_run
            runs = http.get("/api/v1/forward-test/runs").json()["items"]
            assert len(runs) == 1
        assert _shutdown(again) == 0
    finally:
        again.kill()


def test_parent_death_stops_sidecar(sidecar: Sidecar) -> None:
    sidecar.wait_ready()
    assert sidecar.proc.stdin is not None
    sidecar.proc.stdin.close()  # the shell process disappeared
    assert sidecar.wait_exit() == 0


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signal")
def test_sigterm_is_graceful(sidecar: Sidecar) -> None:
    sidecar.wait_ready()
    sidecar.proc.send_signal(signal.SIGTERM)
    # uvicorn shuts down gracefully, then re-raises the signal (exit status -15)
    assert sidecar.wait_exit() in (0, -signal.SIGTERM)
    log = (sidecar.root / "logs" / "backend.log").read_text(encoding="utf-8")
    assert "Application shutdown complete." in log


def test_port_in_use_reports_exit_code(root: Path) -> None:
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen(1)
        port = int(busy.getsockname()[1])
        car = Sidecar(root, port)
        try:
            assert car.wait_exit(60) == 4
        finally:
            car.kill()
