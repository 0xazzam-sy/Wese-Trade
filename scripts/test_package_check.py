#!/usr/bin/env python3
"""Validate the PERSONAL TEST PACKAGE end to end against a real app executable.

    python scripts/test_package_check.py --app "<Wese Trade exe>" --creds credentials.json
                                         [--require-okx] [--label installer]

The app is launched exactly like a user would (no special flags), with a sanitized
environment (no Python / Node on PATH). The harness reads the backend port from the app's
own desktop.log, then checks through the loopback API:

* the three test accounts log in and have the right permissions
  (admin: user management + forward-test controls; analyst: forward-test views only;
  viewer: read-only, no admin or analyst actions)
* frozen strategy version, desktop mode, native data root
* forward-test run exists and was started at launch time (never backdated)
* with --require-okx: OKX connected, symbols, candles (chart data), analysis, signal policy
* the app is closed the normal way (window close on Windows), the backend stops and no
  sidecar process remains; a relaunch keeps the same users and the same forward-test run

Passwords are read from the credentials file and are NEVER printed or logged.
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from desktop_smoke import clean_env, sidecars_running

FROZEN = "wese-trade-forward-4.2-a03e20f1d4"
READY = re.compile(r"backend ready on 127\.0\.0\.1:(\d+)")
RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(
        f"[{'PASS' if ok else 'FAIL'}] {name}{(' - ' + detail) if detail else ''}",
        flush=True,
    )


def data_root() -> Path:
    if os.environ.get("WESE_RUNTIME_ROOT"):
        return Path(os.environ["WESE_RUNTIME_ROOT"])
    if os.name == "nt":
        return Path(os.environ["LOCALAPPDATA"]) / "WeseTrade"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "WeseTrade"
    return Path.home() / ".local" / "share" / "WeseTrade"


class Client:
    def __init__(self, port: int) -> None:
        self.base = f"http://127.0.0.1:{port}/api/v1"
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar)
        )

    def call(
        self, method: str, path: str, body: object | None = None
    ) -> tuple[int, object]:
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with self.opener.open(req, timeout=60) as resp:
                raw = resp.read()
                status = resp.status
        except urllib.error.HTTPError as exc:
            raw, status = exc.read(), exc.code
        try:
            return status, json.loads(raw) if raw else None
        except ValueError:
            return status, raw[:200]


def launch(
    app: Path, log: Path, env: dict[str, str]
) -> tuple[subprocess.Popen[bytes], int]:
    offset = log.stat().st_size if log.exists() else 0
    proc = subprocess.Popen([str(app)], env=env)
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise SystemExit(f"app exited during startup (code {proc.returncode})")
        if log.exists():
            with log.open("rb") as fh:
                fh.seek(offset)
                found = READY.findall(fh.read().decode("utf-8", "replace"))
            if found:
                return proc, int(found[-1])
        time.sleep(0.5)
    proc.kill()
    raise SystemExit("backend never became ready")


def close_app(proc: subprocess.Popen[bytes], log: Path) -> None:
    offset = log.stat().st_size
    if os.name == "nt":
        # the normal way: ask the window to close (no /F), like clicking X
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid)], check=False, capture_output=True
        )
    else:
        proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=60)
        exited = True
    except subprocess.TimeoutExpired:
        proc.kill()
        exited = False
    check("app closes", exited)
    time.sleep(3)
    check("no Wese Trade backend process left", sidecars_running() == 0)
    if os.name == "nt":
        with log.open("rb") as fh:
            fh.seek(offset)
            tail = fh.read().decode("utf-8", "replace")
        check(
            "backend stopped gracefully on close",
            "exiting (backend graceful: true)" in tail,
        )


def login(port: int, account: dict[str, str]) -> Client:
    client = Client(port)
    status, body = client.call(
        "POST",
        "/auth/login",
        {"username": account["username"], "password": account["password"]},
    )
    role = body.get("user", {}).get("role") if isinstance(body, dict) else None
    check(
        f"{account['username']} login",
        status == 200 and role == account["role"],
        f"role={role}",
    )
    return client


def session_checks(
    port: int,
    accounts: dict[str, dict[str, str]],
    launched_at: float,
    require_okx: bool,
    first: bool,
    previous_run: dict | None,
) -> dict | None:
    anon = Client(port)
    status, body = anon.call("GET", "/auth/setup")
    check(
        "prepared accounts present (no first-run screen)",
        body == {"needs_setup": False},
    )
    status, _ = anon.call(
        "POST",
        "/auth/login",
        {"username": "admin_test", "password": "wrong-password-x"},
    )
    check("wrong password rejected", status == 401)

    admin = login(port, accounts["admin"])
    analyst = login(port, accounts["analyst"])
    viewer = login(port, accounts["viewer"])

    status, runtime = admin.call("GET", "/system/runtime")
    ok = isinstance(runtime, dict) and runtime.get("mode") == "desktop"
    check(
        "desktop mode + app version",
        ok,
        f"version={runtime.get('app_version') if ok else '?'}",
    )
    version = (
        runtime.get("strategy", {}).get("version")
        if isinstance(runtime, dict)
        else None
    )
    check("frozen strategy unchanged", version == FROZEN, str(version))
    root = (
        (runtime or {}).get("paths", {}).get("root")
        if isinstance(runtime, dict)
        else None
    )
    check(
        "data in native app-data folder",
        root is not None and Path(root).resolve() == data_root().resolve(),
        str(root),
    )

    status, users = admin.call("GET", "/users")
    names = sorted(u["username"] for u in users["items"]) if status == 200 else []
    check(
        "admin: user management", names == ["admin_test", "analyst_test", "viewer_test"]
    )
    check("analyst: no user management", analyst.call("GET", "/users")[0] == 403)
    check("viewer: no user management", viewer.call("GET", "/users")[0] == 403)

    status, card = viewer.call("GET", "/forward-test/status")
    run = card.get("run") if isinstance(card, dict) else None
    check(
        "forward test run exists",
        status == 200 and run is not None and run["status"] == "forward_testing",
    )
    if run is not None:
        started = datetime.fromisoformat(run["started_at"]).timestamp()
        if first:
            check(
                "forward test started at launch time (not backdated)",
                started >= launched_at - 5,
                run["started_at"],
            )
        else:
            check(
                "forward test run resumed (same run)",
                previous_run is not None and run == previous_run,
                f"run {run['id']}",
            )
    rid = run["id"] if run else 0
    check(
        "admin: forward-test details",
        admin.call("GET", f"/forward-test/runs/{rid}")[0] == 200,
    )
    check(
        "analyst: forward-test details",
        analyst.call("GET", f"/forward-test/runs/{rid}")[0] == 200,
    )
    check(
        "viewer: no forward-test details",
        viewer.call("GET", f"/forward-test/runs/{rid}")[0] == 403,
    )
    check(
        "analyst: no admin controls",
        analyst.call("POST", f"/forward-test/runs/{rid}/pause", {"note": ""})[0] == 403,
    )
    check(
        "viewer: no admin controls",
        viewer.call("POST", f"/forward-test/runs/{rid}/pause", {"note": ""})[0] == 403,
    )
    if first:
        paused = admin.call(
            "POST", f"/forward-test/runs/{rid}/pause", {"note": "package validation"}
        )[0]
        resumed = admin.call(
            "POST", f"/forward-test/runs/{rid}/resume", {"note": "package validation"}
        )[0]
        check("admin: forward-test pause/resume", paused == 200 and resumed == 200)

    if require_okx:
        deadline, state = time.monotonic() + 120, None
        while time.monotonic() < deadline:
            status, st = viewer.call("GET", "/markets/status")
            state = st.get("state") if isinstance(st, dict) else None
            if status == 200 and st.get("available") and state == "connected":
                break
            time.sleep(2)
        check("OKX connected", state == "connected", str(state))
        status, symbols = viewer.call("GET", "/markets/symbols")
        count = len(symbols.get("items", [])) if isinstance(symbols, dict) else 0
        check("symbols load", status == 200 and count > 100, f"{count} contracts")
        for tf in ("15m", "1h"):
            status, candles = viewer.call(
                "GET", f"/markets/BTCUSDT/candles?timeframe={tf}&limit=300"
            )
            n = len(candles.get("candles", [])) if isinstance(candles, dict) else 0
            check(
                f"chart data BTCUSDT {tf}", status == 200 and n >= 100, f"{n} candles"
            )
        status, analysis = viewer.call("GET", "/analysis/ETHUSDT?timeframe=15m")
        check(
            "analysis loads",
            status == 200
            and isinstance(analysis, dict)
            and analysis.get("analysis_ready") is True,
        )
        status, sig15 = viewer.call("GET", "/signals/BTCUSDT?timeframe=15m")
        strat = sig15.get("strategy", {}) if isinstance(sig15, dict) else {}
        check(
            "15m signal-enabled (forward test)",
            status == 200
            and strat.get("signal_capable") is True
            and strat.get("version") == FROZEN,
        )
        status, sig5 = viewer.call("GET", "/signals/BTCUSDT?timeframe=5m")
        strat5 = sig5.get("strategy", {}) if isinstance(sig5, dict) else {}
        check(
            "5m research-only (no directional signals)",
            status == 200 and strat5.get("signal_capable") is False,
        )
    return run


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--creds", type=Path, required=True)
    parser.add_argument("--require-okx", action="store_true")
    parser.add_argument("--label", default="app")
    args = parser.parse_args()
    accounts = {
        a["role"]: a for a in json.loads(args.creds.read_text(encoding="utf-8"))
    }
    env = clean_env(offline=False)
    env.pop("WESE_SMOKE_SETUP", None)
    log = data_root() / "logs" / "desktop.log"
    print(f"== {args.label}: {args.app} (data root {data_root()})", flush=True)

    launched_at = time.time()
    proc, port = launch(args.app, log, env)
    check("app starts + backend auto-starts", True, f"port {port}")
    run = session_checks(port, accounts, launched_at, args.require_okx, True, None)
    close_app(proc, log)

    proc, port = launch(args.app, log, env)
    check("relaunch", True, f"port {port}")
    session_checks(port, accounts, launched_at, False, False, run)
    close_app(proc, log)

    failed = [r for r in RESULTS if not r[1]]
    print(
        f"== {args.label}: {len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed",
        flush=True,
    )
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
