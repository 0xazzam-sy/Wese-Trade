"""Small authenticated encryption for local secrets (e.g. the Telegram bot token).

Standard library only: encrypt-then-MAC with an HMAC-SHA256 counter-mode keystream and an
HMAC-SHA256 tag over (nonce || ciphertext). Keys are derived from the application signing
key with a purpose label, so a token stored in the database is unreadable without the
local secret file. Ciphertexts are url-safe base64 strings prefixed with the format id.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

PREFIX = "sb1:"
_NONCE = 16
_TAG = 32


class SecretBoxError(ValueError):
    """The ciphertext is malformed or was not produced with this key."""


def _keys(master: str, purpose: str) -> tuple[bytes, bytes]:
    root = hashlib.sha256(f"wese-secretbox|{purpose}|{master}".encode()).digest()
    enc = hmac.new(root, b"enc", hashlib.sha256).digest()
    mac = hmac.new(root, b"mac", hashlib.sha256).digest()
    return enc, mac


def _stream(key: bytes, nonce: bytes, n: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < n:
        out += hmac.new(key, nonce + counter.to_bytes(8, "big"), hashlib.sha256).digest()
        counter += 1
    return bytes(out[:n])


def seal(plaintext: str, master: str, purpose: str) -> str:
    enc, mac = _keys(master, purpose)
    nonce = secrets.token_bytes(_NONCE)
    data = plaintext.encode()
    ct = bytes(a ^ b for a, b in zip(data, _stream(enc, nonce, len(data)), strict=True))
    tag = hmac.new(mac, nonce + ct, hashlib.sha256).digest()
    return PREFIX + base64.urlsafe_b64encode(nonce + ct + tag).decode()


def open_(sealed: str, master: str, purpose: str) -> str:
    if not sealed.startswith(PREFIX):
        raise SecretBoxError("unknown secret format")
    try:
        raw = base64.urlsafe_b64decode(sealed[len(PREFIX) :].encode())
    except ValueError as exc:
        raise SecretBoxError("corrupted secret") from exc
    if len(raw) < _NONCE + _TAG:
        raise SecretBoxError("corrupted secret")
    nonce, ct, tag = raw[:_NONCE], raw[_NONCE:-_TAG], raw[-_TAG:]
    enc, mac = _keys(master, purpose)
    if not hmac.compare_digest(tag, hmac.new(mac, nonce + ct, hashlib.sha256).digest()):
        raise SecretBoxError("secret does not match this installation key")
    return bytes(a ^ b for a, b in zip(ct, _stream(enc, nonce, len(ct)), strict=True)).decode()


def mask(secret: str | None, keep: int = 4) -> str:
    """Display form of a secret: never more than the last `keep` characters."""
    if not secret:
        return ""
    tail = secret[-keep:] if len(secret) > 2 * keep else ""
    return f"••••{tail}"
