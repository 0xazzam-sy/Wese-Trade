#!/usr/bin/env python3
"""Build the packaged backend sidecar for the CURRENT platform (Windows / macOS / Linux).

    python scripts/build_sidecar.py            # build frontend + sidecar, then self-test it
    python scripts/build_sidecar.py --skip-web  # reuse frontend/dist

Output: desktop/src-tauri/resources/backend/ (bundled by Tauri as `backend/`).
The self-test starts the built executable on a temporary app-data root, waits for
/api/v1/health, checks the first-run state and stops it through the graceful shutdown hook.
"""

from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
OUT = ROOT / "desktop" / "src-tauri" / "resources"
EXE = "wese-trade-backend.exe" if os.name == "nt" else "wese-trade-backend"
README = (
    "The packaged backend sidecar (PyInstaller one-folder build) is generated here by\n"
    "`python scripts/build_sidecar.py` and bundled as `backend/` inside the app. Not committed.\n"
)


def run(cmd: list[str], cwd: Path) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=cwd, check=True, shell=os.name == "nt" and cmd[0] == "npm")


def build(skip_web: bool) -> Path:
    if not skip_web:
        run(["npm", "ci"], FRONTEND)
        run(["npm", "run", "build"], FRONTEND)
    target = OUT / "backend"
    if target.exists():
        shutil.rmtree(target)
    with tempfile.TemporaryDirectory() as work:
        run(
            [
                sys.executable,
                "-m",
                "PyInstaller",
                "--noconfirm",
                "--clean",
                "--distpath",
                str(OUT),
                "--workpath",
                work,
                str(BACKEND / "packaging" / "wese-trade-backend.spec"),
            ],
            BACKEND,
        )
    (target / "README.md").write_text(
        README, encoding="utf-8"
    )  # the committed placeholder
    return target / EXE


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def self_test(exe: Path) -> None:
    port, token = free_port(), "selftest-token-0123456789abcdef"
    with tempfile.TemporaryDirectory(prefix="Wese Trade selftest ") as root:
        env = {
            **os.environ,
            "WESE_RUNTIME_ROOT": root,
            "WESE_PORT": str(port),
            "WESE_DESKTOP_TOKEN": token,
            "OKX_REST_URL": "http://127.0.0.1:9",  # offline: no network needed
            "OKX_PUBLIC_WS_URL": "ws://127.0.0.1:9",
            "OKX_BUSINESS_WS_URL": "ws://127.0.0.1:9",
            "NEWS_ENABLED": "false",
        }
        proc = subprocess.Popen([str(exe)], cwd=tempfile.gettempdir(), env=env)
        base = f"http://127.0.0.1:{port}"
        try:
            for _ in range(240):
                try:
                    with urllib.request.urlopen(
                        f"{base}/api/v1/health", timeout=1
                    ) as r:
                        if r.status == 200:
                            break
                except OSError:
                    time.sleep(0.5)
            else:
                raise SystemExit("self-test: sidecar never became healthy")
            with urllib.request.urlopen(f"{base}/api/v1/auth/setup", timeout=5) as r:
                assert b'"needs_setup":true' in r.read(), (
                    "fresh install must need setup"
                )
            with urllib.request.urlopen(f"{base}/", timeout=5) as r:
                assert b'<div id="root">' in r.read(), "web app not served"
            req = urllib.request.Request(
                f"{base}/api/v1/system/shutdown",
                method="POST",
                headers={"X-Wese-Desktop-Token": token},
            )
            urllib.request.urlopen(req, timeout=5).close()
            code = proc.wait(timeout=30)
            assert code == 0, f"unexpected exit code {code}"
            assert (Path(root) / "data" / "wese_trade.db").exists()
            print(f"self-test OK: {exe} (port {port}, exit {code})")
        finally:
            if proc.poll() is None:
                proc.kill()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-web", action="store_true")
    parser.add_argument("--skip-test", action="store_true")
    args = parser.parse_args()
    exe = build(args.skip_web)
    if not args.skip_test:
        self_test(exe)


if __name__ == "__main__":
    main()
