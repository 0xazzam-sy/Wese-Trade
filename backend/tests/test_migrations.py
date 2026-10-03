from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from app.core.config import get_settings
from tests.conftest import TEST_SECRET

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _config(db_path: Path) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.attributes["database_url"] = f"sqlite+aiosqlite:///{db_path}"
    config.attributes["configure_logger"] = False
    return config


def test_upgrade_and_downgrade(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECRET_KEY", TEST_SECRET)
    get_settings.cache_clear()
    db_path = tmp_path / "migrate.db"
    config = _config(db_path)

    command.upgrade(config, "head")
    engine = sa.create_engine(f"sqlite:///{db_path}")
    columns = {c["name"] for c in sa.inspect(engine).get_columns("users")}
    assert columns == {
        "id",
        "username",
        "password_hash",
        "role",
        "is_active",
        "created_at",
        "updated_at",
        "last_login_at",
    }

    command.downgrade(config, "base")
    assert "users" not in sa.inspect(engine).get_table_names()
    engine.dispose()
    get_settings.cache_clear()
