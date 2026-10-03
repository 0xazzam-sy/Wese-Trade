"""Password hashing with Argon2id (argon2-cffi defaults follow RFC 9106 recommendations)."""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()

MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 256

# Pre-computed hash used to equalize timing when the username does not exist.
_DUMMY_HASH = _hasher.hash("neuralshot-timing-equalizer")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def burn_verification_time(password: str) -> None:
    """Run a verification against a dummy hash so unknown users take as long as known ones."""
    verify_password(password, _DUMMY_HASH)


def validate_password_strength(password: str) -> list[str]:
    """Return a list of human-readable problems (empty if acceptable)."""
    problems: list[str] = []
    if len(password) < MIN_PASSWORD_LENGTH:
        problems.append(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    if len(password) > MAX_PASSWORD_LENGTH:
        problems.append(f"Password must be at most {MAX_PASSWORD_LENGTH} characters.")
    if password.strip() != password:
        problems.append("Password must not start or end with whitespace.")
    if len(set(password)) < 5:
        problems.append("Password is too repetitive.")
    return problems
