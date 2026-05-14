"""Tests for bcrypt password helpers."""

from __future__ import annotations

from app.security.password import hash_password, verify_password


def test_hash_password_produces_bcrypt_string() -> None:
    h = hash_password("correct-horse-battery-staple")
    assert h.startswith("$2")
    assert len(h) > 20


def test_verify_password_accepts_matching_password() -> None:
    h = hash_password("secret-pass")
    assert verify_password("secret-pass", h) is True


def test_verify_password_rejects_wrong_password() -> None:
    h = hash_password("secret-pass")
    assert verify_password("other-pass", h) is False


def test_hash_uses_distinct_salts() -> None:
    a = hash_password("same-input")
    b = hash_password("same-input")
    assert a != b
    assert verify_password("same-input", a) is True
    assert verify_password("same-input", b) is True


def test_verify_password_rejects_invalid_hash() -> None:
    assert verify_password("x", "not-a-bcrypt-hash") is False


def test_default_cost_embedded_in_hash() -> None:
    """bcrypt encodes work factor in the hash prefix (default 12)."""
    h = hash_password("any-password")
    parts = h.split("$")
    assert parts[1] in ("2b", "2a", "2y")
    assert int(parts[2]) == 12
