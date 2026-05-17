"""Pytest configuration: env vars required before importing the app or JWT helpers."""

from __future__ import annotations

import os

os.environ.setdefault(
    "JWT_SECRET_KEY",
    "pytest-jwt-secret-key-must-be-long-enough-for-hs256-testing",
)
