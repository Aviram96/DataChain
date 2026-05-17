"""Runtime configuration from environment variables."""

from __future__ import annotations

import os


def get_jwt_secret() -> str:
    key = os.getenv("JWT_SECRET_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "JWT_SECRET_KEY is not set. Set it in the environment (see backend/.env.example)."
        )
    return key


def get_jwt_access_token_expire_minutes() -> int:
    raw = os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60")
    try:
        return max(1, min(60 * 24 * 7, int(raw)))  # cap at 7 days
    except ValueError:
        return 60
