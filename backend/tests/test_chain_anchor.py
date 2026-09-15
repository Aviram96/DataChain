"""Tests for Web3.py segment anchoring (CP-D.P3). RPC is mocked."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest

from app.services.chain_anchor import (
    ChainAnchorError,
    SegmentAnchorRequest,
    anchor_segment,
    camera_id_to_bytes16,
    is_retryable_anchor_error,
    sha256_hex_to_bytes32,
    unix_uint64,
)

CAMERA_ID = UUID("01234567-89ab-cdef-0123-456789abcdef")
STARTED = datetime.fromtimestamp(1_700_000_000, tz=timezone.utc)
ENDED = datetime.fromtimestamp(1_700_000_060, tz=timezone.utc)
CID = "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi"
HASH = "aa" * 32
TX = "0x" + "bb" * 32


def _request() -> SegmentAnchorRequest:
    return SegmentAnchorRequest(
        camera_id=CAMERA_ID,
        started_at=STARTED,
        ended_at=ENDED,
        cid=CID,
        segment_hash=HASH,
    )


def test_encodes_camera_id_and_hash() -> None:
    assert len(camera_id_to_bytes16(CAMERA_ID)) == 16
    assert sha256_hex_to_bytes32(HASH) == bytes.fromhex(HASH)
    assert unix_uint64(STARTED) == 1_700_000_000


def test_rejects_zero_segment_hash() -> None:
    with pytest.raises(ChainAnchorError, match="zero"):
        sha256_hex_to_bytes32("00" * 32)


def test_timeout_and_gas_errors_are_retryable() -> None:
    assert is_retryable_anchor_error(TimeoutError("RPC timeout")) is True
    assert is_retryable_anchor_error(RuntimeError("insufficient funds")) is True
    assert is_retryable_anchor_error(RuntimeError("AlreadyAnchored")) is False


def test_anchor_segment_returns_tx_hash() -> None:
    assert (
        anchor_segment(_request(), send_once=lambda _req: TX, max_attempts=1)
        == TX
    )


def test_anchor_retries_timeout_then_succeeds() -> None:
    calls = {"n": 0}

    def send(_req: SegmentAnchorRequest) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError("RPC timeout")
        return TX

    tx = anchor_segment(
        _request(),
        send_once=send,
        max_attempts=3,
        retry_delay_seconds=0,
    )
    assert tx == TX
    assert calls["n"] == 2


def test_anchor_retries_gas_then_raises_without_success() -> None:
    calls = {"n": 0}

    def send(_req: SegmentAnchorRequest) -> str:
        calls["n"] += 1
        raise RuntimeError("intrinsic gas too low")

    with pytest.raises(ChainAnchorError, match="3 attempt"):
        anchor_segment(
            _request(),
            send_once=send,
            max_attempts=3,
            retry_delay_seconds=0,
        )
    assert calls["n"] == 3


def test_anchor_does_not_retry_contract_revert() -> None:
    calls = {"n": 0}

    def send(_req: SegmentAnchorRequest) -> str:
        calls["n"] += 1
        raise RuntimeError("AlreadyAnchored")

    with pytest.raises(ChainAnchorError, match="AlreadyAnchored"):
        anchor_segment(
            _request(),
            send_once=send,
            max_attempts=3,
            retry_delay_seconds=0,
        )
    assert calls["n"] == 1
