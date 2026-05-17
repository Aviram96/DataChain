"""JWT access tokens (HS256)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from app.config import get_jwt_access_token_expire_minutes, get_jwt_secret

ALGORITHM = "HS256"


def create_access_token(subject_user_id: str) -> str:
    """Encode a short-lived access token. ``subject_user_id`` is the user's UUID string."""
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=get_jwt_access_token_expire_minutes())
    payload: dict[str, Any] = {
        "sub": subject_user_id,
        "exp": expire,
        "iat": now,
    }
    return jwt.encode(payload, get_jwt_secret(), algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and validate a token; raises ``jwt.PyJWTError`` subclasses on failure."""
    return jwt.decode(token, get_jwt_secret(), algorithms=[ALGORITHM])
