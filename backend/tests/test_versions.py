"""The application version (SemVer) is declared once per toolchain and must agree.
It is independent of the frozen strategy version."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

from app import __version__
from app.forward_test.candidate import forward_version, frozen_config

ROOT = Path(__file__).resolve().parents[2]
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def test_app_versions_agree() -> None:
    versions = {
        "backend": __version__,
        "pyproject": tomllib.loads((ROOT / "backend/pyproject.toml").read_text())["project"][
            "version"
        ],
        "frontend": json.loads((ROOT / "frontend/package.json").read_text())["version"],
        "desktop": json.loads((ROOT / "desktop/package.json").read_text())["version"],
        "tauri": json.loads((ROOT / "desktop/src-tauri/tauri.conf.json").read_text())["version"],
        "cargo": tomllib.loads((ROOT / "desktop/src-tauri/Cargo.toml").read_text())["package"][
            "version"
        ],
    }
    assert len(set(versions.values())) == 1, versions
    assert SEMVER.match(__version__)


def test_strategy_version_is_separate_and_frozen() -> None:
    assert forward_version(frozen_config()) == "wese-trade-forward-4.2-a03e20f1d4"
    assert __version__ not in "wese-trade-forward-4.2-a03e20f1d4"


def test_updater_never_ships_a_private_key() -> None:
    conf = json.loads((ROOT / "desktop/src-tauri/tauri.conf.json").read_text())
    updater = conf["plugins"]["updater"]
    assert set(updater) <= {"pubkey", "endpoints", "windows"}  # no key material, no bypass
    assert updater["endpoints"] == [
        "https://github.com/0xazzam-sy/Wese-Trade/releases/latest/download/latest.json"
    ]
    for path in ROOT.rglob("*.key"):
        assert "node_modules" in path.parts or "target" in path.parts, path
