"""Password hashing and verification (bcrypt).

All persisted passwords must go through ``hash_password``; login flows use
``verify_password`` against the stored ``password_hash`` column.
"""

from __future__ import annotations

import os

import bcrypt

_DEFAULT_ROUNDS = 12
_MIN_ROUNDS = 4
_MAX_ROUNDS = 31


def _bcrypt_rounds() -> int:
    raw = os.getenv("BCRYPT_ROUNDS")
    if raw is None or raw.strip() == "":
        return _DEFAULT_ROUNDS
    try:
        n = int(raw)
    except ValueError:
        return _DEFAULT_ROUNDS
    return max(_MIN_ROUNDS, min(_MAX_ROUNDS, n))


def hash_password(plain_password: str) -> str:
    """Return a bcrypt hash string suitable for storing in ``password_hash``."""
    rounds = _bcrypt_rounds()
    salt = bcrypt.gensalt(rounds=rounds)
    digest = bcrypt.hashpw(plain_password.encode("utf-8"), salt)
    return digest.decode("utf-8")


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Return True if ``plain_password`` matches the stored bcrypt ``password_hash``."""
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            password_hash.encode("utf-8"),
        )
    except (ValueError, TypeError):
        return False
