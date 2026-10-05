"""Canonical runtime paths: the ONE place that decides where mutable files live.

Two modes:

* ``development`` (default): mutable files go under the git-ignored ``backend/data/runtime``
  (the development database stays wherever ``DATABASE_URL`` points).
* ``desktop``: the packaged app. The desktop shell resolves the native per-user
  application-data directory with the OS API (Tauri path resolver) and passes it as
  ``WESE_RUNTIME_ROOT``. Python never guesses OS-specific locations itself and never
  writes inside the installation directory.

Layout under the root::

    data/       wese_trade.db (+ WAL files), secret_key
    logs/       backend.log, forward-test.log (rotated)
    cache/
    exports/
    backups/    timestamped DB backups taken before migrations
"""

from __future__ import annotations

import os
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]

RUNTIME_MODE_ENV = "WESE_RUNTIME_MODE"
RUNTIME_ROOT_ENV = "WESE_RUNTIME_ROOT"
DATABASE_FILENAME = "wese_trade.db"
SECRET_FILENAME = "secret_key"  # noqa: S105  (a file name, not a secret)


class RuntimeMode(StrEnum):
    DEVELOPMENT = "development"
    DESKTOP = "desktop"


@dataclass(frozen=True, slots=True)
class RuntimePaths:
    root: Path

    @property
    def data(self) -> Path:
        return self.root / "data"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    @property
    def cache(self) -> Path:
        return self.root / "cache"

    @property
    def exports(self) -> Path:
        return self.root / "exports"

    @property
    def backups(self) -> Path:
        return self.root / "backups"

    @property
    def database(self) -> Path:
        return self.data / DATABASE_FILENAME

    @property
    def secret_file(self) -> Path:
        return self.data / SECRET_FILENAME

    def ensure(self) -> RuntimePaths:
        for directory in (self.data, self.logs, self.cache, self.exports, self.backups):
            directory.mkdir(parents=True, exist_ok=True)
        return self


def runtime_mode(environ: Mapping[str, str] = os.environ) -> RuntimeMode:
    value = environ.get(RUNTIME_MODE_ENV, RuntimeMode.DEVELOPMENT.value).strip().lower()
    try:
        return RuntimeMode(value)
    except ValueError as exc:
        raise RuntimeError(f"{RUNTIME_MODE_ENV} must be 'development' or 'desktop'") from exc


def resolve_runtime_paths(environ: Mapping[str, str] = os.environ) -> RuntimePaths:
    root = environ.get(RUNTIME_ROOT_ENV, "").strip()
    if root:
        return RuntimePaths(Path(root).expanduser().resolve())
    if runtime_mode(environ) is RuntimeMode.DESKTOP:
        raise RuntimeError(f"desktop mode requires {RUNTIME_ROOT_ENV} (set by the desktop shell)")
    # Development: inside the git-ignored backend/data folder.
    return RuntimePaths(BACKEND_DIR / "data" / "runtime")


def load_or_create_secret(path: Path) -> str:
    """Per-installation signing secret. Created once (owner-only permissions), never logged."""
    try:
        value = path.read_text(encoding="utf-8").strip()
        if len(value) >= 32:
            return value
    except FileNotFoundError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    value = secrets.token_urlsafe(64)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(value)
    os.replace(tmp, path)
    return value
