"""Datachain contract helpers with Web3.py (Slice D).

``anchor_segment`` submits ``anchorSegment`` and retries RPC timeouts and gas
failures. Failures raise so ingest can keep the temp file.

``get_segment`` is a view call (``getSegment``): no private key, no PostgreSQL.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from eth_account import Account
from web3 import Web3
from web3.exceptions import TimeExhausted

try:
    from web3.middleware import ExtraDataToPOAMiddleware
except ImportError:  # web3 < 6.14
    from web3.middleware import geth_poa_middleware as ExtraDataToPOAMiddleware

from app.config import (
    get_anchor_max_attempts,
    get_anchor_private_key,
    get_anchor_retry_delay_seconds,
    get_anchor_rpc_timeout_seconds,
    get_datachain_contract_address,
    get_polygon_chain_id,
    get_polygon_rpc_url,
)
from app.contracts.datachain_abi import DATACHAIN_ABI

logger = logging.getLogger(__name__)

SendOnce = Callable[["SegmentAnchorRequest"], str]
CallOnce = Callable[[UUID, datetime], "SegmentAnchor"]


class ChainAnchorError(Exception):
    """Anchor write or on-chain read failed."""


@dataclass(frozen=True)
class SegmentAnchorRequest:
    """On-chain fields for one one-minute segment."""

    camera_id: UUID
    started_at: datetime
    ended_at: datetime
    cid: str
    segment_hash: str


@dataclass(frozen=True)
class SegmentAnchor:
    """Decoded ``getSegment`` result (no database)."""

    camera_id: UUID
    started_at: datetime
    ended_at: datetime
    cid: str
    segment_hash: str


def camera_id_to_bytes16(camera_id: UUID) -> bytes:
    raw = camera_id.bytes
    if len(raw) != 16:
        raise ChainAnchorError("camera id must be 16 bytes")
    return raw


def sha256_hex_to_bytes32(segment_hash: str) -> bytes:
    cleaned = segment_hash.strip().removeprefix("0x")
    if len(cleaned) != 64:
        raise ChainAnchorError("segment hash must be 64 hex characters (SHA-256)")
    try:
        raw = bytes.fromhex(cleaned)
    except ValueError as exc:
        raise ChainAnchorError("segment hash is not valid hex") from exc
    if raw == bytes(32):
        raise ChainAnchorError("segment hash must not be zero")
    return raw


def bytes16_to_camera_id(raw: object) -> UUID:
    data = _as_bytes(raw, expected_len=16, label="camera id")
    return UUID(bytes=data)


def bytes32_to_sha256_hex(raw: object) -> str:
    return _as_bytes(raw, expected_len=32, label="segment hash").hex()


def _as_bytes(raw: object, *, expected_len: int, label: str) -> bytes:
    if isinstance(raw, (bytes, bytearray, memoryview)):
        data = bytes(raw)
    else:
        raise ChainAnchorError(f"{label} must be bytes")
    if len(data) != expected_len:
        raise ChainAnchorError(f"{label} must be {expected_len} bytes")
    return data


def decode_segment_anchor(raw: object) -> SegmentAnchor:
    """Turn a Web3.py ``getSegment`` tuple/mapping into ``SegmentAnchor``."""
    camera_raw = _anchor_field(raw, 0, "cameraId", "camera_id")
    started_raw = _anchor_field(raw, 1, "startedAt", "started_at")
    ended_raw = _anchor_field(raw, 2, "endedAt", "ended_at")
    cid_raw = _anchor_field(raw, 3, "cid")
    hash_raw = _anchor_field(raw, 4, "segmentHash", "segment_hash")
    cid = str(cid_raw).strip()
    if not cid:
        raise ChainAnchorError("AnchorNotFound")
    return SegmentAnchor(
        camera_id=bytes16_to_camera_id(camera_raw),
        started_at=datetime.fromtimestamp(int(started_raw), tz=timezone.utc),
        ended_at=datetime.fromtimestamp(int(ended_raw), tz=timezone.utc),
        cid=cid,
        segment_hash=bytes32_to_sha256_hex(hash_raw),
    )


def _anchor_field(raw: object, index: int, *names: str) -> object:
    if isinstance(raw, dict):
        for name in names:
            if name in raw:
                return raw[name]
    if isinstance(raw, (list, tuple)) and len(raw) > index:
        return raw[index]
    for name in names:
        if hasattr(raw, name):
            return getattr(raw, name)
    raise ChainAnchorError("malformed getSegment result")


def unix_uint64(moment: datetime) -> int:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    value = int(moment.timestamp())
    if value < 0:
        raise ChainAnchorError("timestamp must be on or after Unix epoch")
    return value


def is_retryable_anchor_error(exc: BaseException) -> bool:
    """True for RPC timeouts and typical gas / fee failures (CP-D.P3)."""
    if isinstance(exc, (TimeoutError, TimeExhausted)):
        return True
    if isinstance(exc, ChainAnchorError):
        return False
    message = str(exc).lower()
    timeout_marks = ("timeout", "timed out", "time exhausted")
    gas_marks = (
        "insufficient funds",
        "out of gas",
        "intrinsic gas",
        "max fee per gas",
        "gas required exceeds",
        "underpriced",
        "replacement transaction underpriced",
        "nonce too low",
    )
    if any(mark in message for mark in timeout_marks):
        return True
    if any(mark in message for mark in gas_marks):
        return True
    return False


def anchor_segment(
    request: SegmentAnchorRequest,
    *,
    send_once: SendOnce | None = None,
    max_attempts: int | None = None,
    retry_delay_seconds: float | None = None,
) -> str:
    """Send ``anchorSegment`` and return the transaction hash (0x-prefixed).

    Does not delete files or write PostgreSQL. After failed retries, raises
    ``ChainAnchorError`` so the segment can stay in ``temp/``.
    """
    attempts = (
        max_attempts if max_attempts is not None else get_anchor_max_attempts()
    )
    delay = (
        retry_delay_seconds
        if retry_delay_seconds is not None
        else get_anchor_retry_delay_seconds()
    )
    send = send_once if send_once is not None else _send_anchor_once
    last_error: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            tx_hash = send(request)
        except Exception as exc:
            last_error = exc
            retryable = is_retryable_anchor_error(exc)
            if retryable and attempt < attempts:
                logger.warning(
                    "Anchor attempt %s/%s failed (%s); retrying without dropping "
                    "the segment: %s",
                    attempt,
                    attempts,
                    type(exc).__name__,
                    exc,
                )
                time.sleep(delay)
                continue
            logger.error(
                "Anchor failed for camera %s start %s after %s attempt(s); "
                "segment is not proven on-chain",
                request.camera_id,
                request.started_at.isoformat(),
                attempt,
            )
            raise ChainAnchorError(
                f"Anchor failed after {attempt} attempt(s): {exc}"
            ) from exc
        logger.info(
            "Anchored camera %s start %s tx=%s",
            request.camera_id,
            request.started_at.isoformat(),
            tx_hash,
        )
        return tx_hash
    raise ChainAnchorError(f"Anchor failed: {last_error}")


def get_segment(
    camera_id: UUID,
    started_at: datetime,
    *,
    call_once: CallOnce | None = None,
) -> SegmentAnchor:
    """Read ``getSegment`` for one camera and start time.

    Does not use PostgreSQL or a signing key. Missing anchors and RPC failures
    raise ``ChainAnchorError``.
    """
    call = call_once if call_once is not None else _call_get_segment_once
    try:
        anchored = call(camera_id, started_at)
    except ChainAnchorError:
        raise
    except Exception as exc:
        logger.error(
            "On-chain segment read failed for camera %s start %s: %s",
            camera_id,
            started_at.isoformat(),
            exc,
        )
        raise ChainAnchorError(f"On-chain segment read failed: {exc}") from exc
    logger.info(
        "Read on-chain segment camera %s start %s cid=%s",
        camera_id,
        started_at.isoformat(),
        anchored.cid,
    )
    return anchored


def _connected_web3() -> tuple[Web3, float]:
    timeout = get_anchor_rpc_timeout_seconds()
    w3 = Web3(
        Web3.HTTPProvider(
            get_polygon_rpc_url(),
            request_kwargs={"timeout": timeout},
        )
    )
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    if not w3.is_connected():
        raise TimeoutError("Polygon RPC is not reachable")
    return w3, timeout


def _datachain_contract(w3: Web3):
    return w3.eth.contract(
        address=Web3.to_checksum_address(get_datachain_contract_address()),
        abi=DATACHAIN_ABI,
    )


def _call_get_segment_once(camera_id: UUID, started_at: datetime) -> SegmentAnchor:
    w3, _timeout = _connected_web3()
    contract = _datachain_contract(w3)
    raw = contract.functions.getSegment(
        camera_id_to_bytes16(camera_id),
        unix_uint64(started_at),
    ).call()
    return decode_segment_anchor(raw)


def _send_anchor_once(request: SegmentAnchorRequest) -> str:
    if not request.cid.strip():
        raise ChainAnchorError("CID is empty")
    started = unix_uint64(request.started_at)
    ended = unix_uint64(request.ended_at)
    if ended <= started:
        raise ChainAnchorError("end time must be after start time")

    w3, timeout = _connected_web3()
    account = Account.from_key(get_anchor_private_key())
    contract = _datachain_contract(w3)
    nonce = w3.eth.get_transaction_count(account.address)
    tx = contract.functions.anchorSegment(
        camera_id_to_bytes16(request.camera_id),
        started,
        ended,
        request.cid.strip(),
        sha256_hex_to_bytes32(request.segment_hash),
    ).build_transaction(
        {
            "from": account.address,
            "nonce": nonce,
            "chainId": get_polygon_chain_id(),
        }
    )
    signed = account.sign_transaction(tx)
    raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
    tx_hash = w3.eth.send_raw_transaction(raw)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=int(timeout))
    status = int(receipt["status"])
    if status != 1:
        raise RuntimeError(
            "anchor transaction failed (status 0; possible gas issue)"
        )
    hex_hash = tx_hash.hex() if hasattr(tx_hash, "hex") else str(tx_hash)
    if not hex_hash.startswith("0x"):
        hex_hash = f"0x{hex_hash}"
    return hex_hash
