#!/usr/bin/env python3
"""PERSONAL TEST PACKAGE ONLY: build a fresh seed database with three local test accounts.

    python scripts/make_test_seed.py <out_dir>

Writes:
  <out_dir>/TestData/wese_trade.db   fresh schema (Alembic head) + admin_test / analyst_test /
                                     viewer_test (Argon2 hashes only). No forward-test run,
                                     no signals, no history: the app starts the run itself at the
                                     real current UTC time on first launch.
  <out_dir>/credentials.json         the generated passwords (for the package's
                                     TEST-ACCOUNTS-AR.txt and for automated validation).

Passwords are random, never printed, never logged and never written anywhere else. This tool
is not part of the application: production first-run behaviour is unchanged (an empty
database still shows the first-run administrator setup).
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import sqlite3
import string
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("SECRET_KEY", secrets.token_urlsafe(48))  # only to load settings

ACCOUNTS = (
    ("admin_test", "admin"),
    ("analyst_test", "analyst"),
    ("viewer_test", "viewer"),
)
# Unambiguous characters only (no 0/O, 1/l/I) so the passwords are easy to type correctly.
ALPHABET = "".join(c for c in string.ascii_letters + string.digits if c not in "0O1lI")
SYMBOLS = "@#%+=?"


def make_password(length: int = 18) -> str:
    while True:
        body = [secrets.choice(ALPHABET) for _ in range(length - 2)]
        body += [secrets.choice(SYMBOLS), secrets.choice(string.digits[2:])]
        secrets.SystemRandom().shuffle(body)
        password = "".join(body)
        if (
            any(c.islower() for c in password)
            and any(c.isupper() for c in password)
            and len(set(password)) >= 10
        ):
            return password


async def seed(db_path: Path, credentials: dict[str, str]) -> None:
    from app.core.config import Settings
    from app.db.session import Database
    from app.models.user import UserRole
    from app.services.user_service import create_user

    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{db_path.as_posix()}",
        market_data_enabled=False,
        news_enabled=False,
        weather_enabled=False,
        _env_file=None,
    )
    database = Database(settings)
    try:
        async with database.session_factory() as session:
            for username, role in ACCOUNTS:
                await create_user(
                    session,
                    username=username,
                    password=credentials[username],
                    role=UserRole(role),
                )
    finally:
        await database.dispose()


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    out = Path(sys.argv[1]).resolve()
    data = out / "TestData"
    data.mkdir(parents=True, exist_ok=True)
    db = data / "wese_trade.db"
    if db.exists():
        raise SystemExit(f"refusing to overwrite {db}")

    from app.db.migrate import head_revision, prepare_database

    prepare_database(db, out / "backups-unused")
    credentials = {username: make_password() for username, _ in ACCOUNTS}
    asyncio.run(seed(db, credentials))

    # one self-contained file: no -wal/-shm next to it
    conn = sqlite3.connect(db)
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("PRAGMA journal_mode=DELETE")
        users = conn.execute(
            "SELECT username, role, is_active FROM users ORDER BY id"
        ).fetchall()
        runs = conn.execute("SELECT count(*) FROM forward_test_runs").fetchone()[0]
        signals = conn.execute("SELECT count(*) FROM forward_test_signals").fetchone()[
            0
        ]
        revision = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    finally:
        conn.close()
    for suffix in ("-wal", "-shm"):
        Path(f"{db}{suffix}").unlink(missing_ok=True)

    assert [u[0] for u in users] == [a[0] for a in ACCOUNTS]
    assert [u[1] for u in users] == [a[1] for a in ACCOUNTS]
    assert runs == 0 and signals == 0, "seed must not contain any forward-test data"
    assert revision == head_revision()

    creds_file = out / "credentials.json"
    fd = os.open(creds_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(
            [
                {"username": u, "role": r, "password": credentials[u]}
                for u, r in ACCOUNTS
            ],
            fh,
        )
    print(f"seed OK: {db} ({len(users)} users, schema {revision}, 0 forward-test runs)")


if __name__ == "__main__":
    main()
