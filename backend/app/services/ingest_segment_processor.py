"""Process a staged ingest segment: IPFS, chain anchor, then DB (Slice D).

The stored window comes from ``resolve_segment_utc_window``. PostgreSQL keeps
that precise server-time range. The chain anchor uses the same instants,
floored to whole seconds by ``unix_uint64``.

Returns True only after the CID is on-chain and the VideoRecord is saved, so
the worker can delete the temp file. ``SegmentTimelineNotReady`` is left for
the worker to retry. Permanent timeline and anchor conflicts are raised so
the MP4 is kept and not processed again.

A matching anchor that is already on-chain is saved without a second
transaction. ``getSegment`` does not return the original transaction hash, so
that recovered row may have a null ``tx_hash``. An unrelated anchor or a
different recording in the same whole second is left unchanged.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy.orm import Session, sessionmaker

from app.models.video_record import VideoRecord
from app.services.chain_anchor import (
    ChainAnchorError,
    SegmentAnchor,
    SegmentAnchorRequest,
    anchor_segment,
    get_segment,
    unix_uint64,
)
from app.services.pinata_ipfs import PinataUploadError, upload_segment
from app.services.segment_identity import SegmentIdentityError, parse_segment_path
from app.services.segment_integrity import (
    SegmentIntegrityError,
    probe_video_timing,
    sha256_file,
)
from app.services.segment_timeline import resolve_segment_utc_window
from app.services.video_chunker import DEFAULT_CHUNK_DURATION_SECONDS

logger = logging.getLogger(__name__)

UploadFn = Callable[[Path], str]
AnchorFn = Callable[[SegmentAnchorRequest], str]
ReadAnchorFn = Callable[[UUID, datetime], SegmentAnchor]


class IngestProcessingError(Exception):
    """IPFS, chain, or DB step failed for a staged segment."""


class IngestPermanentError(Exception):
    """Retrying this segment would conflict with an existing record or anchor."""


def persist_video_record(
    db: Session,
    *,
    camera_id: UUID,
    started_at: datetime,
    ended_at: datetime,
    ipfs_cid: str,
    segment_hash: str,
    tx_hash: str | None,
) -> VideoRecord:
    """Insert the row for this camera and start time.

    An existing row is reused only when it is the same CID and hash. Its
    times and content are not rewritten. A missing transaction hash may be
    filled when this attempt has one.
    """
    existing = _record_at_start(db, camera_id, started_at)
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
    if not _same_content(existing, ipfs_cid, segment_hash):
        raise IngestPermanentError(
            "A stored record already uses this start time for different content"
        )
    if existing.tx_hash is None and tx_hash:
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
    read_anchor: ReadAnchorFn | None = None,
) -> bool:
    """Upload to Pinata, anchor on-chain, save VideoRecord. False keeps temp file."""
    try:
        identity = parse_segment_path(path, duration_seconds=duration_seconds)
    except SegmentIdentityError as exc:
        logger.error("Cannot process unnamed segment %s: %s", path.name, exc)
        return False

    try:
        file_start_time, file_duration = probe_video_timing(path)
    except SegmentIntegrityError as exc:
        logger.error("Cannot determine timing for %s: %s", path.name, exc)
        return False

    window = resolve_segment_utc_window(
        path.parent,
        path.name,
        file_start_time=file_start_time,
        file_duration=file_duration,
    )
    started_at = window.started_at
    ended_at = window.ended_at
    if not _chain_window_is_valid(started_at, ended_at):
        raise IngestPermanentError(
            "Blockchain time window is invalid or collapses to one second: "
            f"{path.name}"
        )

    try:
        digest = sha256_file(path)
    except OSError as exc:
        logger.error("Cannot hash %s: %s", path.name, exc)
        return False

    if session_factory is None:
        logger.error("No database session for %s; keeping temp file", path.name)
        return False

    read = read_anchor if read_anchor is not None else get_segment
    upload_fn = upload if upload is not None else upload_segment
    anchor_fn = send_anchor if send_anchor is not None else anchor_segment
    db = session_factory()
    try:
        _reject_conflicting_records(
            db,
            camera_id=identity.camera_id,
            started_at=started_at,
            segment_hash=digest,
        )
        existing = _record_at_start(db, identity.camera_id, started_at)
        if existing is not None:
            return _finish_existing_record(
                db,
                path,
                existing=existing,
                digest=digest,
                send_anchor=anchor_fn,
                read_anchor=read,
            )

        cid, tx_hash = _publish_new_segment(
            path,
            camera_id=identity.camera_id,
            started_at=started_at,
            ended_at=ended_at,
            digest=digest,
            upload=upload_fn,
            send_anchor=anchor_fn,
            read_anchor=read,
        )
        if cid is None:
            return False
        persist_video_record(
            db,
            camera_id=identity.camera_id,
            started_at=started_at,
            ended_at=ended_at,
            ipfs_cid=cid,
            segment_hash=digest,
            tx_hash=tx_hash,
        )
    except IngestPermanentError:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        logger.exception("Database save failed for %s; keeping temp file", path.name)
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


def _finish_existing_record(
    db: Session,
    path: Path,
    *,
    existing: VideoRecord,
    digest: str,
    send_anchor: AnchorFn,
    read_anchor: ReadAnchorFn,
) -> bool:
    """Reuse a stored row. Do not upload a second CID or change its content.

    The anchor uses the times already stored. A later timeline mapping must
    not rewrite that row or submit a different window over it.
    """
    started_at = _as_utc(existing.started_at)
    ended_at = _as_utc(existing.ended_at)
    try:
        anchored = _read_anchor(read_anchor, existing.camera_id, started_at)
    except ChainAnchorError as exc:
        logger.warning(
            "Chain read failed for %s; keeping temp file for retry: %s",
            path.name,
            exc,
        )
        return False

    if anchored is not None:
        if not _anchor_matches(
            anchored,
            camera_id=existing.camera_id,
            started_at=started_at,
            ended_at=ended_at,
            cid=existing.ipfs_cid,
            segment_hash=digest,
        ):
            raise IngestPermanentError(
                f"On-chain anchor conflicts with stored record for {path.name}"
            )
        return True

    if not _chain_window_is_valid(started_at, ended_at):
        raise IngestPermanentError(
            f"Stored record has an invalid blockchain window for {path.name}"
        )

    request = SegmentAnchorRequest(
        camera_id=existing.camera_id,
        started_at=started_at,
        ended_at=ended_at,
        cid=existing.ipfs_cid,
        segment_hash=digest,
    )
    try:
        tx_hash = send_anchor(request)
    except (ChainAnchorError, RuntimeError) as exc:
        if "AlreadyAnchored" not in str(exc):
            logger.warning(
                "Chain anchor failed for stored %s; keeping temp file: %s",
                path.name,
                exc,
            )
            return False
        if not _confirmed_anchor(
            read_anchor,
            camera_id=existing.camera_id,
            started_at=started_at,
            ended_at=ended_at,
            cid=existing.ipfs_cid,
            digest=digest,
        ):
            return False
        tx_hash = None
    persist_video_record(
        db,
        camera_id=existing.camera_id,
        started_at=started_at,
        ended_at=_as_utc(existing.ended_at),
        ipfs_cid=existing.ipfs_cid,
        segment_hash=digest,
        tx_hash=tx_hash,
    )
    return True


def _publish_new_segment(
    path: Path,
    *,
    camera_id: UUID,
    started_at: datetime,
    ended_at: datetime,
    digest: str,
    upload: UploadFn,
    send_anchor: AnchorFn,
    read_anchor: ReadAnchorFn,
) -> tuple[str | None, str | None]:
    """Upload and anchor a segment that has no database row yet."""
    try:
        anchored = _read_anchor(read_anchor, camera_id, started_at)
    except ChainAnchorError as exc:
        logger.warning(
            "Chain read failed for %s; keeping temp file for retry: %s",
            path.name,
            exc,
        )
        return None, None

    if anchored is not None:
        if not _anchor_matches(
            anchored,
            camera_id=camera_id,
            started_at=started_at,
            ended_at=ended_at,
            cid=anchored.cid,
            segment_hash=digest,
        ):
            raise IngestPermanentError(
                f"On-chain anchor conflicts with {path.name}"
            )
        return anchored.cid, None

    try:
        cid = upload(path)
    except (PinataUploadError, RuntimeError, OSError) as exc:
        logger.warning(
            "IPFS upload failed for %s; keeping temp file for retry: %s",
            path.name,
            exc,
        )
        return None, None

    request = SegmentAnchorRequest(
        camera_id=camera_id,
        started_at=started_at,
        ended_at=ended_at,
        cid=cid,
        segment_hash=digest,
    )
    try:
        tx_hash = send_anchor(request)
    except (ChainAnchorError, RuntimeError) as exc:
        if "AlreadyAnchored" not in str(exc):
            logger.warning(
                "Chain anchor failed for %s (cid=%s); keeping temp file: %s",
                path.name,
                cid,
                exc,
            )
            return None, None
        if not _confirmed_anchor(
            read_anchor,
            camera_id=camera_id,
            started_at=started_at,
            ended_at=ended_at,
            cid=cid,
            digest=digest,
        ):
            return None, None
        tx_hash = None
    return cid, tx_hash


def _confirmed_anchor(
    read_anchor: ReadAnchorFn,
    *,
    camera_id: UUID,
    started_at: datetime,
    ended_at: datetime,
    cid: str,
    digest: str,
) -> bool:
    """True when the on-chain row is this segment. A mismatch is permanent."""
    try:
        anchored = _read_anchor(read_anchor, camera_id, started_at)
    except ChainAnchorError as exc:
        logger.warning("Chain read failed while confirming an anchor: %s", exc)
        return False
    if anchored is None:
        return False
    if _anchor_matches(
        anchored,
        camera_id=camera_id,
        started_at=started_at,
        ended_at=ended_at,
        cid=cid,
        segment_hash=digest,
    ):
        return True
    raise IngestPermanentError("Existing chain anchor does not match this segment")


def _reject_conflicting_records(
    db: Session,
    *,
    camera_id: UUID,
    started_at: datetime,
    segment_hash: str,
) -> None:
    """Refuse a different recording that floors to this chain timestamp.

    The chain key is a whole second, which is not its own database column.
    Rows for this camera are compared by that floored instant.
    """
    second = unix_uint64(started_at)
    rows = db.query(VideoRecord).filter(VideoRecord.camera_id == camera_id).all()
    for row in rows:
        if unix_uint64(_as_utc(row.started_at)) != second:
            continue
        if _as_utc(row.started_at) != _as_utc(started_at):
            raise IngestPermanentError(
                "Another recording already occupies this blockchain timestamp"
            )
        if row.segment_hash != segment_hash:
            raise IngestPermanentError(
                "A stored record already uses this start time for different content"
            )


def _record_at_start(
    db: Session,
    camera_id: UUID,
    started_at: datetime,
) -> VideoRecord | None:
    target = _as_utc(started_at)
    rows = db.query(VideoRecord).filter(VideoRecord.camera_id == camera_id).all()
    for row in rows:
        if _as_utc(row.started_at) == target:
            return row
    return None


def _read_anchor(
    read_anchor: ReadAnchorFn,
    camera_id: UUID,
    started_at: datetime,
) -> SegmentAnchor | None:
    try:
        return read_anchor(camera_id, started_at)
    except ChainAnchorError as exc:
        if "AnchorNotFound" in str(exc):
            return None
        raise


def _anchor_matches(
    anchored: SegmentAnchor,
    *,
    camera_id: UUID,
    started_at: datetime,
    ended_at: datetime,
    cid: str,
    segment_hash: str,
) -> bool:
    return (
        anchored.camera_id == camera_id
        and unix_uint64(anchored.started_at) == unix_uint64(started_at)
        and unix_uint64(anchored.ended_at) == unix_uint64(ended_at)
        and anchored.cid == cid
        and anchored.segment_hash.lower() == segment_hash.lower()
    )


def _same_content(row: VideoRecord, cid: str, segment_hash: str) -> bool:
    return row.ipfs_cid == cid and row.segment_hash == segment_hash


def _chain_window_is_valid(started_at: datetime, ended_at: datetime) -> bool:
    try:
        return unix_uint64(ended_at) > unix_uint64(started_at)
    except ChainAnchorError:
        return False


def _as_utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)
