"""Tests for JWT access token helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
import pytest

from app.security.jwt_tokens import ALGORITHM, create_access_token, decode_access_token


def test_create_and_decode_roundtrip() -> None:
    uid = str(uuid4())
    token = create_access_token(uid)
    payload = decode_access_token(token)
    assert payload["sub"] == uid
    assert "exp" in payload


def test_decode_rejects_wrong_signing_key() -> None:
    exp = datetime.now(timezone.utc) + timedelta(hours=1)
    token = jwt.encode(
        {"sub": str(uuid4()), "exp": exp},
        "wrong-secret-not-the-apps-key",
        algorithm=ALGORITHM,
    )
    with pytest.raises(jwt.InvalidSignatureError):
        decode_access_token(token)


def test_decode_rejects_tampered_token() -> None:
    token = create_access_token(str(uuid4()))
    bad = token[:-8] + "xxxxxxxx"
    with pytest.raises(jwt.PyJWTError):
        decode_access_token(bad)


def test_decode_rejects_expired_token() -> None:
    from app.config import get_jwt_secret

    past = datetime.now(timezone.utc) - timedelta(seconds=1)
    token = jwt.encode(
        {"sub": str(uuid4()), "exp": past},
        get_jwt_secret(),
        algorithm=ALGORITHM,
    )
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_access_token(token)
