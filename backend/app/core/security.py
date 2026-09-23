"""Password hashing + JWT helpers for the auth endpoints.

- Passwords: PBKDF2-SHA256 (stdlib ``hashlib``), 240k iterations, 16-byte
  random salt per hash, stored as
  ``pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>``. Verification is
  constant-time (``hmac.compare_digest``). Never plaintext, never reversible.
- Tokens: compact HS256 JWTs (PyJWT) whose ``sub`` claim is the user's UUID,
  signed with ``JWT_SECRET`` and expiring after ``JWT_EXPIRE_MINUTES``.
  Verification failures raise ``ValueError``; the API layer maps those to
  401-style client errors rather than leaking internals.
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
import secrets
import uuid
from typing import Any

import jwt

_PBKDF2_ITERATIONS = 240_000
_SALT_BYTES = 16
_HASH_BYTES = 32
_HASH_NAME = "pbkdf2_sha256"


def _settings() -> Any:
    from app.core.config import get_settings

    return get_settings()


def create_password_hash(plain: str) -> str:
    """Hash a plaintext password (random salt, PBKDF2-SHA256)."""
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", plain.encode(), salt, _PBKDF2_ITERATIONS)
    return f"{_HASH_NAME}${_PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(plain: str, hashed: str) -> bool:
    """Constant-time verification; False for malformed/stale hashes."""
    try:
        name, iterations, salt_hex, digest_hex = hashed.split("$")
        if name != _HASH_NAME:
            return False
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.pbkdf2_hmac(
            "sha256", plain.encode(), bytes.fromhex(salt_hex), int(iterations)
        )
    except (ValueError, AttributeError):
        return False
    return hmac.compare_digest(actual, expected)


def create_access_token(user_id: uuid.UUID) -> str:
    """Mint a signed JWT for ``user_id`` (HS256, ``sub`` = str(uuid))."""
    settings = _settings()
    now = datetime.datetime.now(datetime.UTC)
    claims: dict[str, Any] = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + datetime.timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> uuid.UUID:
    """Return the user id from a valid token; raise ValueError otherwise."""
    settings = _settings()
    try:
        payload = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
        return uuid.UUID(str(payload["sub"]))
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise ValueError("invalid or expired token") from exc
