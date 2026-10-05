"""Canonical runtime paths, desktop settings and the per-installation secret."""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.runtime import (
    RuntimeMode,
    RuntimePaths,
    load_or_create_secret,
    resolve_runtime_paths,
    runtime_mode,
)


@pytest.mark.parametrize("name", ["WeseTrade", "مستخدم تجريبي/Wese Trade", "user name/ünï"])
def test_layout_with_spaces_and_non_ascii(tmp_path: Path, name: str) -> None:
    paths = resolve_runtime_paths({"WESE_RUNTIME_ROOT": str(tmp_path / name)}).ensure()
    assert paths.root == (tmp_path / name).resolve()
    for sub in ("data", "logs", "cache", "exports", "backups"):
        assert (paths.root / sub).is_dir()
    assert paths.database == paths.root / "data" / "wese_trade.db"


def test_modes() -> None:
    assert runtime_mode({}) is RuntimeMode.DEVELOPMENT
    assert runtime_mode({"WESE_RUNTIME_MODE": "Desktop"}) is RuntimeMode.DESKTOP
    with pytest.raises(RuntimeError):
        runtime_mode({"WESE_RUNTIME_MODE": "cloud"})
    with pytest.raises(RuntimeError, match="WESE_RUNTIME_ROOT"):
        resolve_runtime_paths({"WESE_RUNTIME_MODE": "desktop"})
    dev = resolve_runtime_paths({})
    assert dev.root.parts[-2:] == ("data", "runtime")  # git-ignored backend/data


def test_secret_created_once_owner_only(tmp_path: Path) -> None:
    path = tmp_path / "data" / "secret_key"
    first = load_or_create_secret(path)
    assert len(first) >= 64
    assert load_or_create_secret(path) == first
    if sys.platform != "win32":
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


def _desktop(tmp_path: Path, **kw: object) -> Settings:
    return Settings(
        runtime_mode=RuntimeMode.DESKTOP,
        runtime_root=tmp_path / "Wese Trade",
        app_env="production",
        _env_file=None,
        **kw,  # type: ignore[arg-type]
    )


def test_desktop_settings_use_runtime_db_secret_and_loopback(tmp_path: Path) -> None:
    settings = _desktop(tmp_path)
    paths = RuntimePaths((tmp_path / "Wese Trade").resolve())
    assert settings.sqlite_path == paths.database
    assert settings.signing_key == paths.secret_file.read_text()
    assert settings.cookie_secure is False  # same-origin http://127.0.0.1
    assert settings.uses_placeholder_secret is False
    with pytest.raises(ValueError, match="loopback"):
        _desktop(tmp_path, app_host="0.0.0.0")  # noqa: S104


def test_placeholder_secret_still_rejected_in_production(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="SECRET_KEY"):
        _desktop(tmp_path, secret_key="CHANGE_ME" + "x" * 40)
