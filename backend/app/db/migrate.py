"""Startup database preparation for the packaged (desktop) runtime.

1. Detect the current schema revision.
2. If a migration is needed AND the database already holds data, take a consistent
   backup first (SQLite online-backup API, safe with WAL) into ``backups/``.
3. Run Alembic ``upgrade head``.
4. If the migration fails, restore the original file from that backup and re-raise:
   the user's data is never lost and never deleted automatically.

Only a limited number of timestamped backups is kept (oldest pruned first).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

from app.core.logging import get_logger
from app.core.runtime import BACKEND_DIR

logger = get_logger(__name__)

ALEMBIC_DIR = BACKEND_DIR / "alembic"
KEEP_BACKUPS = 10
BACKUP_PREFIX = "wese_trade-"


class MigrationError(RuntimeError):
    """Migration failed; the original database has been restored."""


@dataclass(frozen=True, slots=True)
class MigrationResult:
    from_revision: str | None
    to_revision: str
    backup: Path | None

    @property
    def migrated(self) -> bool:
        return self.from_revision != self.to_revision


def alembic_config(db_path: Path) -> Config:
    config = Config()
    config.set_main_option("script_location", str(ALEMBIC_DIR))
    config.attributes["database_url"] = f"sqlite+aiosqlite:///{db_path.as_posix()}"
    config.attributes["configure_logger"] = False
    return config


def head_revision() -> str:
    head = ScriptDirectory.from_config(alembic_config(Path("unused.db"))).get_current_head()
    if head is None:  # pragma: no cover - the project always has migrations
        raise MigrationError("no migrations found")
    return head


def current_revision(db_path: Path) -> str | None:
    if not db_path.exists():
        return None
    engine = sa.create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        with engine.connect() as conn:
            return MigrationContext.configure(conn).get_current_revision()
    finally:
        engine.dispose()


def _has_tables(db_path: Path) -> bool:
    if not db_path.exists():
        return False
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()
    finally:
        conn.close()
    return bool(row and row[0])


def backup_database(db_path: Path, backups: Path, label: str) -> Path:
    backups.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    target = backups / f"{BACKUP_PREFIX}{stamp}-{label}.db"
    source = sqlite3.connect(db_path)
    dest = sqlite3.connect(target)
    try:
        source.backup(dest)  # consistent copy, including committed WAL content
    finally:
        dest.close()
        source.close()
    prune_backups(backups)
    return target


def prune_backups(backups: Path, keep: int = KEEP_BACKUPS) -> None:
    files = sorted(backups.glob(f"{BACKUP_PREFIX}*.db"))
    for old in files[:-keep] if keep > 0 else files:
        old.unlink(missing_ok=True)


def _restore(backup: Path, db_path: Path) -> None:
    """Copy the backup back INTO the live database (WAL-safe online-backup API)."""
    source = sqlite3.connect(backup)
    dest = sqlite3.connect(db_path)
    try:
        source.backup(dest)
    finally:
        dest.close()
        source.close()


def prepare_database(db_path: Path, backups: Path) -> MigrationResult:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    head = head_revision()
    current = current_revision(db_path)
    if current == head:
        return MigrationResult(current, head, None)
    backup = None
    if _has_tables(db_path):
        backup = backup_database(db_path, backups, label=f"before-{head}")
        logger.info("db.backup_created", extra={"fields": {"backup": backup.name}})
    try:
        command.upgrade(alembic_config(db_path), "head")
    except Exception as exc:
        if backup is not None:
            _restore(backup, db_path)
            logger.error("db.migration_failed_restored", extra={"fields": {"error": str(exc)}})
        raise MigrationError(f"database migration failed: {exc}") from exc
    logger.info("db.migrated", extra={"fields": {"from": current, "to": head}})
    return MigrationResult(current, head, backup)
