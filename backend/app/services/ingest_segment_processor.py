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
import subprocess
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models.camera import Camera
from app.models.video_record import VideoRecord
from app.services.chain_anchor import (
    ChainAnchorError,
    ChainAnchorNotFoundError,
    SegmentAnchor,
    SegmentAnchorRequest,
    anchor_segment,
    get_segment,
    unix_uint64,
)
from app.services.pinata_ipfs import PinataUploadError, upload_segment
from app.services.segment_identity import SegmentIdentityError, parse_segment_path
from app.services.cctv_feed_simulator import DEFAULT_FFMPEG
from app.services.segment_integrity import (
    DEFAULT_FFPROBE,
    SegmentIntegrityError,
    probe_video_timing,
    sha256_file,
)
from app.services.segment_timeline import resolve_segment_utc_window
from app.services.video_chunker import DEFAULT_CHUNK_DURATION_SECONDS

logger = logging.getLogger(__name__)

# A container start at or below this is already at media time zero for playback.
# The observed stall comes from a start several seconds later, so this does not
# remux a file whose first sample is only a timebase tick past zero.
_START_ALREADY_ZERO_SECONDS = 0.001
# Timebase rounding can move a copied duration by a millisecond or two.
# Fifty milliseconds still rejects a remux that drops or adds the leading gap.
_DURATION_TOLERANCE_SECONDS = 0.05
_NORMALIZED_DIRNAME = ".segment-normalized"

UploadFn = Callable[[Path], str]
AnchorFn = Callable[[SegmentAnchorRequest], str]
ReadAnchorFn = Callable[[UUID, datetime], SegmentAnchor]


class IngestProcessingError(Exception):
    """IPFS, chain, or DB step failed for a staged segment."""


class IngestPermanentError(Exception):
    """Retrying this segment would conflict with an existing record or anchor."""


class CameraNotRecordable(Exception):
    """The camera is archived or gone, so a new recording must not be stored."""


def publishing_allowed(db: Session, camera_id: UUID) -> bool:
    """True only when a fresh read shows the camera is still active.

    A database error fails closed: the caller must not upload or anchor.
    The camera row is refreshed so an archive committed after this session
    started is visible. This cannot cover a chain transaction that is already
    in flight after the check returns True.
    """
    try:
        camera = db.get(Camera, camera_id)
        if camera is not None:
            db.refresh(camera)
    except Exception:
        logger.exception(
            "Cannot confirm camera %s is active; not publishing a new segment",
            camera_id,
        )
        try:
            db.rollback()
        except Exception:
            logger.exception("Could not roll back after a failed camera activity check")
        return False
    if camera is None or camera.deleted_at is not None:
        logger.info(
            "Camera %s is archived or missing; not publishing a new segment",
            camera_id,
        )
        return False
    return True


class SegmentNormalizationError(Exception):
    """The playback copy could not be produced or did not match the source."""


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

    On PostgreSQL the camera row is locked for the insert. An archived or
    missing camera does not receive a new recording.
    """
    if _active_camera_for_insert(db, camera_id) is None:
        raise CameraNotRecordable(camera_id)
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


def _active_camera_for_insert(db: Session, camera_id: UUID) -> Camera | None:
    """Return the camera when it is still active, locking the row on PostgreSQL."""
    stmt = select(Camera).where(Camera.id == camera_id)
    if db.get_bind().dialect.name == "postgresql":
        stmt = stmt.with_for_update()
    camera = db.execute(stmt).scalar_one_or_none()
    if camera is None or camera.deleted_at is not None:
        return None
    return camera


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

    if session_factory is None:
        logger.error("No database session for %s; keeping temp file", path.name)
        return False

    read = read_anchor if read_anchor is not None else get_segment
    upload_fn = upload if upload is not None else upload_segment
    anchor_fn = send_anchor if send_anchor is not None else anchor_segment
    db = session_factory()
    publish_path = path
    remove_publish_copy = False
    try:
        existing = _record_at_start(db, identity.camera_id, started_at)
        if existing is not None:
            # A saved row already names the CID and hash. Do not remux or
            # publish a second file over that recording.
            return _finish_existing_record(
                db,
                path,
                existing=existing,
                digest=existing.segment_hash,
                send_anchor=anchor_fn,
                read_anchor=read,
            )
        if not publishing_allowed(db, identity.camera_id):
            return False

        try:
            publish_path = normalize_segment_media(
                path,
                file_start_time=file_start_time,
                file_duration=file_duration,
            )
        except SegmentNormalizationError as exc:
            logger.warning(
                "Could not normalize %s for playback; keeping source: %s",
                path.name,
                exc,
            )
            return False
        remove_publish_copy = publish_path != path

        try:
            digest = sha256_file(publish_path)
        except OSError as exc:
            logger.error("Cannot hash %s: %s", publish_path.name, exc)
            return False

        _reject_conflicting_records(
            db,
            camera_id=identity.camera_id,
            started_at=started_at,
            segment_hash=digest,
        )
        cid, tx_hash = _publish_new_segment(
            db,
            publish_path,
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
    except CameraNotRecordable:
        db.rollback()
        logger.info(
            "Camera %s is not active; not saving %s",
            identity.camera_id,
            path.name,
        )
        return False
    except Exception:
        db.rollback()
        logger.exception("Database save failed for %s; keeping temp file", path.name)
        return False
    finally:
        if remove_publish_copy:
            _delete_normalized_copy(publish_path)
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

    if not publishing_allowed(db, existing.camera_id):
        logger.info(
            "Not anchoring stored %s; camera %s is not active",
            path.name,
            existing.camera_id,
        )
        return False

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
    db: Session,
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
            raise IngestPermanentError(f"On-chain anchor conflicts with {path.name}")
        return anchored.cid, None

    if not publishing_allowed(db, camera_id):
        return None, None
    try:
        cid = upload(path)
    except (PinataUploadError, RuntimeError, OSError) as exc:
        logger.warning(
            "IPFS upload failed for %s; keeping temp file for retry: %s",
            path.name,
            exc,
        )
        return None, None

    if not publishing_allowed(db, camera_id):
        logger.warning(
            "Camera %s was archived after IPFS upload of %s (cid=%s); "
            "not anchoring. That IPFS object is left unreferenced",
            camera_id,
            path.name,
            cid,
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
    except ChainAnchorNotFoundError:
        return None


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


def normalization_ffmpeg_command(
    source: Path,
    destination: Path,
    *,
    ffmpeg_executable: str = DEFAULT_FFMPEG,
) -> list[str]:
    """Stream-copy a segment so its first sample is at media time zero.

    Metadata is omitted and the muxer is bit-exact so a retry produces the
    same bytes, and therefore the same SHA-256, after a partial publish.
    Every input stream is kept.
    """
    return [
        ffmpeg_executable,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(source),
        "-map",
        "0",
        "-c",
        "copy",
        "-avoid_negative_ts",
        "make_zero",
        "-map_metadata",
        "-1",
        "-muxpreload",
        "0",
        "-muxdelay",
        "0",
        "-fflags",
        "+bitexact",
        "-f",
        "mp4",
        str(destination),
    ]


def normalize_segment_media(
    source: Path,
    *,
    file_start_time: float,
    file_duration: float,
    ffmpeg_executable: str = DEFAULT_FFMPEG,
    ffprobe_executable: str = DEFAULT_FFPROBE,
) -> Path:
    """Return the file to publish. The source is never modified.

    A segment that already starts at media time zero is returned as-is.
    Otherwise a sibling copy is written under ``.segment-normalized``.
    The caller deletes that copy. A failed copy is deleted here.
    """
    if file_start_time <= _START_ALREADY_ZERO_SECONDS:
        return source

    destination = source.parent / _NORMALIZED_DIRNAME / source.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    command = normalization_ffmpeg_command(
        source,
        destination,
        ffmpeg_executable=ffmpeg_executable,
    )
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        _delete_normalized_copy(destination)
        raise SegmentNormalizationError(
            f"FFmpeg could not normalize {source.name}"
        ) from exc
    if completed.returncode != 0 or not destination.is_file():
        _delete_normalized_copy(destination)
        detail = (completed.stderr or "").strip() or "FFmpeg remux failed"
        raise SegmentNormalizationError(detail)

    try:
        _require_playable_copy(
            source,
            destination,
            file_duration=file_duration,
            ffprobe_executable=ffprobe_executable,
        )
    except SegmentNormalizationError:
        _delete_normalized_copy(destination)
        raise
    return destination


def _require_playable_copy(
    source: Path,
    destination: Path,
    *,
    file_duration: float,
    ffprobe_executable: str,
) -> None:
    try:
        start_time, duration = probe_video_timing(
            destination,
            ffprobe_executable=ffprobe_executable,
        )
    except (SegmentIntegrityError, OSError) as exc:
        raise SegmentNormalizationError(
            f"Could not probe normalized {destination.name}"
        ) from exc
    if start_time > _START_ALREADY_ZERO_SECONDS:
        raise SegmentNormalizationError(
            f"Normalized start time is {start_time:.6f}, not zero"
        )
    if abs(duration - file_duration) > _DURATION_TOLERANCE_SECONDS:
        raise SegmentNormalizationError(
            "Normalized duration "
            f"{duration:.6f} differs from source duration {file_duration:.6f}"
        )
    source_streams = _playback_stream_counts(
        source, ffprobe_executable=ffprobe_executable
    )
    normalized_streams = _playback_stream_counts(
        destination, ffprobe_executable=ffprobe_executable
    )
    if source_streams is None or normalized_streams is None:
        raise SegmentNormalizationError(f"Could not read streams for {source.name}")
    source_video, source_audio = source_streams
    normalized_video, normalized_audio = normalized_streams
    if normalized_video < 1 or normalized_video != source_video:
        raise SegmentNormalizationError(
            f"Normalized video streams for {source.name} do not match the source"
        )
    if normalized_audio != source_audio:
        raise SegmentNormalizationError(
            f"Normalized audio streams for {source.name} do not match the source"
        )


def _playback_stream_counts(
    path: Path,
    *,
    ffprobe_executable: str,
) -> tuple[int, int] | None:
    """Return ``(video_count, audio_count)``, or None when ffprobe cannot answer."""
    command = [
        ffprobe_executable,
        "-v",
        "error",
        "-show_entries",
        "stream=codec_type",
        "-of",
        "csv=p=0",
        str(path),
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if completed.returncode != 0:
        return None
    kinds = [
        line.strip().lower() for line in completed.stdout.splitlines() if line.strip()
    ]
    return kinds.count("video"), kinds.count("audio")


def _delete_normalized_copy(path: Path) -> None:
    """Delete a normalized sibling. Never delete the source segment."""
    if path.parent.name != _NORMALIZED_DIRNAME:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("Could not delete normalized copy %s: %s", path, exc)
        return
    try:
        path.parent.rmdir()
    except OSError:
        return
