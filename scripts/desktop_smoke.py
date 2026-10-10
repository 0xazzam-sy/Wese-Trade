#!/usr/bin/env python3
"""CI harness for the INSTALLED desktop app (Windows / macOS / Linux).

    python scripts/desktop_smoke.py "<path to installed app executable>" [--offline]

The app is launched with a sanitized environment (no Python, no Node on PATH, no dev
variables), so it must run entirely from its own bundle. It runs `--smoke-test` twice:

1. first launch: fresh app-data directory, creates the first admin, starts the forward test
2. second launch: same user logs in, the SAME forward-test run is resumed (no duplicate)

After each launch it verifies the backend exited gracefully and no sidecar process is left.
Uses the real native app-data directory unless WESE_RUNTIME_ROOT is set by the caller.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SIDECAR = "wese-trade-backend"


def clean_env(offline: bool) -> dict[str, str]:
    keep = {
        "SYSTEMROOT",
        "WINDIR",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "LOCALAPPDATA",
        "APPDATA",
        "HOME",
        "USER",
        "LOGNAME",
        "DISPLAY",
        "XAUTHORITY",
        "XDG_RUNTIME_DIR",
        "DBUS_SESSION_BUS_ADDRESS",
        "WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS",
        "WEBKIT_DISABLE_COMPOSITING_MODE",
        "WESE_RUNTIME_ROOT",
        "COMPUTERNAME",
        "PROGRAMDATA",
        "PROGRAMFILES",
        "HOMEDRIVE",
        "HOMEPATH",
        "TMPDIR",
        "SSL_CERT_FILE",
        "HTTPS_PROXY",
        "HTTP_PROXY",
        "NO_PROXY",
        "RUST_BACKTRACE",  # diagnostics only (never set by default)
    }
    env = {k: v for k, v in os.environ.items() if k.upper() in keep}
    if os.name == "nt":
        root = os.environ.get("SYSTEMROOT", r"C:\Windows")
        env["PATH"] = os.pathsep.join(
            [rf"{root}\System32", root, rf"{root}\System32\Wbem"]
        )
    else:
        env["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin"
    if offline:
        env.update(
            OKX_REST_URL="http://127.0.0.1:9",
            OKX_PUBLIC_WS_URL="ws://127.0.0.1:9",
            OKX_BUSINESS_WS_URL="ws://127.0.0.1:9",
            NEWS_ENABLED="false",
        )
    env["WESE_SMOKE_SETUP"] = "1"
    return env


def sidecars_running() -> int:
    if os.name == "nt":
        out = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {SIDECAR}.exe", "/NH"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout
        return out.lower().count(f"{SIDECAR}.exe")
    out = subprocess.run(
        ["pgrep", "-x", SIDECAR[:15]], capture_output=True, text=True, check=False
    )
    return len(out.stdout.split())


def no_python_or_node(env: dict[str, str]) -> None:
    import shutil

    for tool in ("python", "python3", "node", "npm"):
        found = shutil.which(tool, path=env["PATH"])
        if found and os.name == "nt":
            raise SystemExit(f"sanitized PATH still exposes {tool}: {found}")
        if found:
            print(
                f"note: system {tool} present at {found} (OS-provided); the app does not use it"
            )


def launch(app: Path, env: dict[str, str], report: Path, extra: dict[str, str]) -> dict:
    started = time.monotonic()
    proc = subprocess.run(
        [str(app), "--smoke-test", str(report)],
        env={**env, **extra},
        timeout=300,
        check=False,
    )
    data = json.loads(report.read_text(encoding="utf-8"))
    data["_exit"] = proc.returncode
    data["_seconds"] = round(time.monotonic() - started, 1)
    return data


def main() -> None:
    # Reports contain Arabic text: never depend on the console code page (cp1252 on Windows).
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app", type=Path)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--crash", action="store_true", help="also test crash recovery")
    args = parser.parse_args()
    env = clean_env(args.offline)
    no_python_or_node(env)
    work = Path(tempfile.mkdtemp(prefix="wese-smoke-"))

    first = launch(
        args.app,
        env,
        work / "first.json",
        {"WESE_SMOKE_CRASH": "1" if args.crash else "0"},
    )
    print(json.dumps(first, ensure_ascii=False, indent=1))
    assert first["_exit"] == 0 and first["ok"], "first launch failed"
    assert first["needs_setup_at_start"] is True, "expected a fresh installation"
    assert first["account"]["status"] == 201
    assert first["runtime"]["mode"] == "desktop"
    assert first["runtime"]["strategy"]["version"].startswith("wese-trade-strategy-4.3-")
    assert (
        first["runtime"]["baseline"]["version"] == "wese-trade-forward-4.2-a03e20f1d4"
    ), "the frozen Strategy 4.2 baseline must be unchanged"
    assert first["forward_run"]["status"] == "forward_testing"
    assert first["backend_stopped_gracefully"] is True
    time.sleep(2)
    assert sidecars_running() == 0, "orphan sidecar after first launch"

    second = launch(args.app, env, work / "second.json", {})
    print(json.dumps(second, ensure_ascii=False, indent=1))
    assert second["_exit"] == 0 and second["ok"], "second launch failed"
    assert second["needs_setup_at_start"] is False
    assert second["account"]["status"] == 200, "user did not persist"
    assert second["forward_run"] == first["forward_run"], "forward-test run not resumed"
    assert second["root"] == first["root"]
    time.sleep(2)
    assert sidecars_running() == 0, "orphan sidecar after second launch"

    root = Path(first["root"])
    expected = os.environ.get("WESE_RUNTIME_ROOT")
    if not expected:
        if os.name == "nt":
            expected = str(Path(os.environ["LOCALAPPDATA"]) / "WeseTrade")
        elif sys.platform == "darwin":
            expected = str(
                Path.home() / "Library" / "Application Support" / "WeseTrade"
            )
    if expected:
        assert Path(expected).resolve() == root.resolve(), (expected, root)
    for sub in ("data", "logs", "cache", "exports", "backups"):
        assert (root / sub).is_dir(), sub
    for log in ("desktop.log", "backend.log", "forward-test.log"):
        assert (root / "logs" / log).exists(), log
    print(f"desktop smoke OK: {args.app} (data root {root})")


if __name__ == "__main__":
    main()
