"""Create the initial administrator account.

Usage (from backend/ with the virtualenv active):

    python -m app.scripts.create_admin                     # interactive prompts
    python -m app.scripts.create_admin --username admin    # prompts for the password only
    printf '%s' "$PW" | python -m app.scripts.create_admin --username admin --password-stdin

By default this refuses to run when any user already exists (initial bootstrap only).
Pass --additional to add another admin to a non-empty database.
Passwords are never accepted as command-line arguments (they would leak into shell history).
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys

from sqlalchemy.exc import OperationalError

from app.auth.passwords import MIN_PASSWORD_LENGTH
from app.core.config import get_settings
from app.db.session import Database
from app.models.user import UserRole
from app.services.user_service import UserServiceError, count_users, create_user


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a NeuralShot administrator account.")
    parser.add_argument("--username", help="Admin username (3-64 chars: letters, digits, _ . -)")
    parser.add_argument(
        "--password-stdin",
        action="store_true",
        help="Read the password from standard input instead of prompting.",
    )
    parser.add_argument(
        "--additional",
        action="store_true",
        help="Allow creating an admin even if users already exist.",
    )
    return parser.parse_args(argv)


def _read_password(from_stdin: bool) -> str:
    if from_stdin:
        return sys.stdin.read().rstrip("\r\n")
    password = getpass.getpass(f"Password (min {MIN_PASSWORD_LENGTH} chars): ")
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        raise SystemExit("error: passwords do not match.")
    return password


async def _main(args: argparse.Namespace) -> int:
    database = Database(get_settings())
    try:
        async with database.session_factory() as session:
            try:
                existing = await count_users(session)
            except OperationalError:
                print(
                    "error: database is not initialised. Run `alembic upgrade head` first.",
                    file=sys.stderr,
                )
                return 2
            if existing and not args.additional:
                print(
                    f"error: {existing} user(s) already exist. "
                    "Use --additional to create another admin.",
                    file=sys.stderr,
                )
                return 1

            username = args.username or (await asyncio.to_thread(input, "Admin username: "))
            password = await asyncio.to_thread(_read_password, args.password_stdin)
            try:
                user = await create_user(
                    session, username=username, password=password, role=UserRole.ADMIN
                )
            except UserServiceError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 1
            print(f"Admin user '{user.username}' created (id={user.id}).")
            return 0
    finally:
        await database.dispose()


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_main(_parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
