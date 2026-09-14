"""Runtime configuration from environment variables."""

from __future__ import annotations

import os


def get_jwt_secret() -> str:
    key = os.getenv("JWT_SECRET_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "JWT_SECRET_KEY is not set. Set it in the environment "
            "(see backend/.env.example)."
        )
    return key


def get_jwt_access_token_expire_minutes() -> int:
    raw = os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60")
    try:
        return max(1, min(60 * 24 * 7, int(raw)))  # cap at 7 days
    except ValueError:
        return 60


def get_camera_probe_timeout_seconds() -> float:
    raw = os.getenv("CAMERA_PROBE_TIMEOUT_SECONDS", "2")
    try:
        return max(0.5, min(10.0, float(raw)))
    except ValueError:
        return 2.0


def get_pinata_jwt() -> str:
    token = os.getenv("PINATA_JWT", "").strip()
    if not token:
        raise RuntimeError(
            "PINATA_JWT is not set. Set it in the environment "
            "(see backend/.env.example)."
        )
    return token


def get_pinata_timeout_seconds() -> float:
    raw = os.getenv("PINATA_TIMEOUT_SECONDS", "120")
    try:
        return max(5.0, min(600.0, float(raw)))
    except ValueError:
        return 120.0
