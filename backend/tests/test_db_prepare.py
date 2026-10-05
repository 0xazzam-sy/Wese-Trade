"""Startup DB preparation: fresh DB, existing DB + backup, failed migration restore."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command

from app.core.config import get_settings
from app.db import migrate
from tests.conftest import TEST_SECRET


@pytest.fixture(autouse=True)
def _secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECRET_KEY", TEST_SECRET)
    get_settings.cache_clear()


def test_fresh_database_migrates_without_backup(tmp_path: Path) -> None:
    db = tmp_path / "data" / "wese_trade.db"
    result = migrate.prepare_database(db, tmp_path / "backups")
    assert result.from_revision is None
    assert result.to_revision == migrate.head_revision()
    assert result.backup is None
    assert migrate.current_revision(db) == migrate.head_revision()
    # idempotent: second start does nothing
    again = migrate.prepare_database(db, tmp_path / "backups")
    assert not again.migrated
    assert list((tmp_path / "backups").glob("*.db")) == []


def test_existing_database_is_backed_up_then_upgraded(tmp_path: Path) -> None:
    db = tmp_path / "wese_trade.db"
    command.upgrade(migrate.alembic_config(db), "0002_signals")
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO users (username, password_hash, role, is_active, created_at, updated_at)"
            " VALUES ('keep', 'h', 'admin', 1, '2026-01-01', '2026-01-01')"
        )
    result = migrate.prepare_database(db, tmp_path / "backups")
    assert result.from_revision == "0002_signals"
    assert result.backup is not None and result.backup.exists()
    with sqlite3.connect(result.backup) as conn:  # the backup holds the original data
        assert conn.execute("SELECT username FROM users").fetchall() == [("keep",)]
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT username FROM users").fetchall() == [("keep",)]
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "forward_test_runs" in tables


def test_failed_migration_restores_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "wese_trade.db"
    command.upgrade(migrate.alembic_config(db), "0002_signals")
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO users (username, password_hash, role, is_active, created_at, updated_at)"
            " VALUES ('precious', 'h', 'admin', 1, '2026-01-01', '2026-01-01')"
        )

    def broken(config: object, revision: str) -> None:
        with sqlite3.connect(db) as conn:  # partially applied, then crash
            conn.execute("DELETE FROM users")
        raise RuntimeError("boom")

    monkeypatch.setattr(command, "upgrade", broken)
    with pytest.raises(migrate.MigrationError):
        migrate.prepare_database(db, tmp_path / "backups")
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT username FROM users").fetchall() == [("precious",)]
    assert migrate.current_revision(db) == "0002_signals"


def test_backups_are_pruned(tmp_path: Path) -> None:
    backups = tmp_path / "backups"
    backups.mkdir()
    for i in range(15):
        (backups / f"wese_trade-2026010{i:02d}T000000Z-x.db").write_bytes(b"")
    (backups / "user-file.db").write_bytes(b"")  # unrelated files are never touched
    migrate.prune_backups(backups, keep=10)
    kept = sorted(p.name for p in backups.glob("wese_trade-*.db"))
    assert len(kept) == 10 and kept[0].startswith("wese_trade-2026010" + "05")
    assert (backups / "user-file.db").exists()


def test_schema_constraints(tmp_path: Path) -> None:
    db = tmp_path / "wese_trade.db"
    migrate.prepare_database(db, tmp_path / "backups")
    engine = sa.create_engine(f"sqlite:///{db}")
    inspector = sa.inspect(engine)
    fks = {fk["referred_table"] for fk in inspector.get_foreign_keys("forward_test_signals")}
    assert fks == {"forward_test_runs"}
    assert {fk["referred_table"] for fk in inspector.get_foreign_keys("forward_test_outcomes")} == {
        "forward_test_runs",
        "forward_test_signals",
    }
    unique = {i["name"] for i in inspector.get_indexes("forward_test_signals") if i["unique"]}
    assert "uq_forward_test_signal" in unique
    run_idx = {i["name"]: i for i in inspector.get_indexes("forward_test_runs")}
    assert run_idx["uq_forward_test_runs_open_version"]["unique"]
    user_unique = [i for i in inspector.get_indexes("users") if i["unique"]] + [
        c for c in inspector.get_unique_constraints("users")
    ]
    assert any("username" in (c.get("column_names") or []) for c in user_unique)
    engine.dispose()
    # round trip: full downgrade then upgrade again
    command.downgrade(migrate.alembic_config(db), "base")
    command.upgrade(migrate.alembic_config(db), "head")
    assert migrate.current_revision(db) == migrate.head_revision()
