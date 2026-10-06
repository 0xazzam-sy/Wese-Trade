#!/usr/bin/env python3
"""UI check of an INSTALLED release build (Windows / macOS CI, exact final artifact).

    python scripts/release_ui_check.py "<installed app executable>" --out <screenshot dir>

Launches the app normally on a fresh data root (WESE_RUNTIME_ROOT), reads the backend port
from the app's desktop.log, runs the chart-signal browser E2E (scripts/e2e_chart_signals.mjs:
first-run admin, real OKX, both charts, legend, layers, analysis-only timeframes, and the
deterministic frozen-engine BUY/SELL fixture rendered in test mode only), then closes the
app and checks that no backend process is left. No credentials are printed.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from desktop_smoke import clean_env
from test_package_check import RESULTS, check, close_app, data_root, launch

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app", type=Path)
    parser.add_argument("--out", type=Path, default=ROOT / "release-ui")
    args = parser.parse_args()
    if not os.environ.get("WESE_RUNTIME_ROOT"):
        raise SystemExit("set WESE_RUNTIME_ROOT to a fresh data root")
    env = clean_env(offline=False)
    env.pop("WESE_SMOKE_SETUP", None)
    log = data_root() / "logs" / "desktop.log"
    proc, port = launch(args.app, log, env)
    check("installed app starts + backend auto-starts", True, f"port {port}")
    time.sleep(2)
    node = subprocess.run(
        [
            "node",
            str(ROOT / "scripts" / "e2e_chart_signals.mjs"),
            "--url",
            f"http://127.0.0.1:{port}",
            "--out",
            str(args.out),
        ],
        check=False,
    )
    check("chart signal E2E on the installed app", node.returncode == 0)
    close_app(proc, log)
    failed = [r for r in RESULTS if not r[1]]
    print(
        f"== release UI check: {len(RESULTS) - len(failed)}/{len(RESULTS)} passed",
        flush=True,
    )
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
