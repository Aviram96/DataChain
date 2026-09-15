"""Process a staged ingest segment: IPFS, chain anchor, then DB (Slice D).

Returns True only after CID + on-chain tx + VideoRecord persist so the
worker can delete the temp file (CP-C.P7). Failures return False and keep
the file for retry. Ingest does not treat the segment as proven without a
tx hash (CP-D.P7).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy.orm import Session, sessionmaker

from app.models.video_record import VideoRecord
from app.services.chain_anchor import (
    ChainAnchorError,
    SegmentAnchorRequest,
    anchor_segment,
)
from app.services.pinata_ipfs import PinataUploadError, upload_segment
from app.services.segment_identity import SegmentIdentityError, parse_segment_path
from app.services.segment_integrity import sha256_file
from app.services.video_chunker import DEFAULT_CHUNK_DURATION_SECONDS

logger = logging.getLogger(__name__)

UploadFn = Callable[[Path], str]
AnchorFn = Callable[[SegmentAnchorRequest], str]


class IngestProcessingError(Exception):
    """IPFS, chain, or DB step failed for a staged segment."""


def persist_video_record(
    db: Session,
    *,
    camera_id: UUID,
    started_at: datetime,
    ended_at: datetime,
    ipfs_cid: str,
    segment_hash: str,
    tx_hash: str,
) -> VideoRecord:
    """Insert or update the row for this camera + start time."""
    existing = (
        db.query(VideoRecord)
        .filter(
            VideoRecord.camera_id == camera_id,
            VideoRecord.started_at == started_at,
        )
        .one_or_none()
    )
    if existing is None:
        record = VideoRecord(
            id=uuid4(),
            camera_id=camera_id,
            started_at=started_at,
            ended_at=ended_at,
            ipfs_cid=ipfs_cid,
            segment_hash=segment_hash,
            tx_hash=tx_hash,
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        return record
    existing.ended_at = ended_at
    existing.ipfs_cid = ipfs_cid
    existing.segment_hash = segment_hash
    existing.tx_hash = tx_hash
    db.commit()
    db.refresh(existing)
    return existing


def process_ingest_segment(
    path: Path,
    *,
    duration_seconds: int = DEFAULT_CHUNK_DURATION_SECONDS,
    session_factory: sessionmaker | None = None,
    upload: UploadFn | None = None,
    send_anchor: AnchorFn | None = None,
) -> bool:
    """Upload to Pinata, anchor on-chain, save VideoRecord. False keeps temp file."""
    try:
        identity = parse_segment_path(path, duration_seconds=duration_seconds)
    except SegmentIdentityError as exc:
        logger.error("Cannot process unnamed segment %s: %s", path.name, exc)
        return False

    try:
        digest = sha256_file(path)
    except OSError as exc:
        logger.error("Cannot hash %s: %s", path.name, exc)
        return False

    upload_fn = upload if upload is not None else upload_segment
    try:
        cid = upload_fn(path)
    except (PinataUploadError, RuntimeError, OSError) as exc:
        logger.warning(
            "IPFS upload failed for %s; keeping temp file for retry: %s",
            path.name,
            exc,
        )
        return False

    request = SegmentAnchorRequest(
        camera_id=identity.camera_id,
        started_at=identity.started_at,
        ended_at=identity.ended_at,
        cid=cid,
        segment_hash=digest,
    )
    anchor_fn = send_anchor if send_anchor is not None else anchor_segment
    try:
        tx_hash = anchor_fn(request)
    except (ChainAnchorError, RuntimeError) as exc:
        logger.warning(
            "Chain anchor failed for %s (cid=%s); keeping temp file for retry: %s",
            path.name,
            cid,
            exc,
        )
        return False

    if session_factory is None:
        logger.error(
            "No database session for %s; keeping temp file (cid=%s tx=%s)",
            path.name,
            cid,
            tx_hash,
        )
        return False

    db = session_factory()
    try:
        persist_video_record(
            db,
            camera_id=identity.camera_id,
            started_at=identity.started_at,
            ended_at=identity.ended_at,
            ipfs_cid=cid,
            segment_hash=digest,
            tx_hash=tx_hash,
        )
    except Exception:
        db.rollback()
        logger.exception(
            "Database save failed for %s; keeping temp file (cid=%s tx=%s)",
            path.name,
            cid,
            tx_hash,
        )
        return False
    finally:
        db.close()

    logger.info(
        "Processed segment %s cid=%s tx=%s",
        path.name,
        cid,
        tx_hash,
    )
    return True
