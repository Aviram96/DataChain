"""Verify stored recordings against the chain and the IPFS file bytes.

Callers pass a camera and a time window. Each stored segment that overlaps
the window is checked on its own. Gaps are the parts of that window that no
stored segment covers, using the segments' real start and end times. Watch
and download both call this before serving a file.
"""

from __future__ import annotations

import logging
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.video_record import VideoRecord
from app.services.chain_anchor import (
    ChainAnchorError,
    ChainAnchorNotFoundError,
    SegmentAnchor,
    get_segment,
    unix_uint64,
)
from app.services.playback_timing import log_playback_step
from app.services.recording_download import RecordingDownloadError, fetch_cid_to_file
from app.services.segment_integrity import sha256_file
from app.services.video_chunker import resolve_temp_dir

logger = logging.getLogger(__name__)

VerifyStatus = Literal[
    "verified",
    "tampered",
    "missing",
    "unavailable",
    "failed",
]

ReadAnchor = Callable[[UUID, datetime], SegmentAnchor]
FetchFile = Callable[[str, Path], None]
HashFile = Callable[[Path], str]

_VERIFIED = "Metadata and file content match the blockchain anchor."
_TAMPERED_METADATA = (
    "Stored camera, time range, CID, or hash does not match the blockchain anchor."
)
_TAMPERED_FILE = "The retrieved video does not match the on-chain SHA-256 hash."
_MISSING_ANCHOR = "No blockchain anchor exists for this recording."
_UNAVAILABLE = "The video file could not be retrieved from IPFS."
_FAILED_CHAIN = (
    "Verification could not be completed because the blockchain read failed."
)
_FAILED_HASH = (
    "Verification could not be completed because the file hash could not be calculated."
)
_MISSING_COVERAGE = "No recording covers this part of the requested range."
# Timestamp seams below this are treated as continuous. A real hole of
# 1 millisecond or longer is still reported as uncovered.
_MIN_UNCOVERED_GAP = timedelta(milliseconds=1)

_WORST_FIRST: tuple[VerifyStatus, ...] = (
    "tampered",
    "failed",
    "unavailable",
    "missing",
)


class RecordingVerificationError(Exception):
    """The requested window cannot be verified."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


@dataclass(frozen=True)
class SegmentVerification:
    """One stored segment that overlaps the requested window."""

    video_record_id: UUID
    started_at: datetime
    ended_at: datetime
    status: VerifyStatus
    detail: str
    ipfs_cid: str
    segment_hash: str


@dataclass(frozen=True)
class MissingInterval:
    """Part of the request that no stored segment covers."""

    started_at: datetime
    ended_at: datetime
    detail: str


@dataclass(frozen=True)
class ExcludedInterval:
    """Part of the request covered by a segment that must not be played."""

    started_at: datetime
    ended_at: datetime
    status: VerifyStatus
    video_record_id: UUID
    detail: str


@dataclass(frozen=True)
class EligibleSegment:
    """A segment whose metadata and file bytes both matched."""

    video_record_id: UUID
    started_at: datetime
    ended_at: datetime
    ipfs_cid: str
    segment_hash: str
    path: Path


@dataclass(frozen=True)
class RecordingVerification:
    """Per-segment results, coverage gaps, and the segments safe to serve."""

    overall: VerifyStatus
    segments: tuple[SegmentVerification, ...]
    missing_intervals: tuple[MissingInterval, ...]
    excluded_intervals: tuple[ExcludedInterval, ...]
    eligible: tuple[EligibleSegment, ...]
    work_dir: Path


def verify_recording_range(
    db: Session,
    camera_id: UUID,
    started_at: datetime,
    ended_at: datetime,
    *,
    work_dir: Path | None = None,
    read_anchor: ReadAnchor | None = None,
    fetch_file: FetchFile | None = None,
    hash_file: HashFile | None = None,
) -> RecordingVerification:
    """Verify every stored segment that overlaps ``[started_at, ended_at)``.

    ``eligible`` contains only segments whose chain metadata and IPFS SHA-256
    both matched. A chain or IPFS failure is never reported as verified.
    """
    window_start = _as_utc(started_at)
    window_end = _as_utc(ended_at)
    if window_end <= window_start:
        raise RecordingVerificationError("End time must be after start time.")

    directory = work_dir if work_dir is not None else _make_work_dir()
    directory.mkdir(parents=True, exist_ok=True)
    read = read_anchor if read_anchor is not None else get_segment
    fetch = fetch_file if fetch_file is not None else fetch_cid_to_file
    digest_file = hash_file if hash_file is not None else sha256_file

    lookup_started = time.perf_counter()
    records = _overlapping_records(db, camera_id, window_start, window_end)
    log_playback_step(
        "database_overlap",
        lookup_started,
        rows=len(records),
    )
    segments: list[SegmentVerification] = []
    eligible: list[EligibleSegment] = []
    for record in records:
        outcome, path = _verify_record(
            record,
            camera_id=camera_id,
            directory=directory,
            read_anchor=read,
            fetch_file=fetch,
            hash_file=digest_file,
        )
        segments.append(outcome)
        if outcome.status == "verified" and path is not None:
            eligible.append(
                EligibleSegment(
                    video_record_id=record.id,
                    started_at=_as_utc(record.started_at),
                    ended_at=_as_utc(record.ended_at),
                    ipfs_cid=record.ipfs_cid,
                    segment_hash=record.segment_hash,
                    path=path,
                )
            )

    gaps = tuple(
        MissingInterval(
            started_at=start,
            ended_at=end,
            detail=_MISSING_COVERAGE,
        )
        for start, end in _uncovered_intervals(window_start, window_end, records)
    )
    excluded: list[ExcludedInterval] = []
    for segment in segments:
        if segment.status == "verified":
            continue
        clipped = _clip(
            segment.started_at,
            segment.ended_at,
            window_start,
            window_end,
        )
        if clipped is None:
            continue
        clipped_start, clipped_end = clipped
        excluded.append(
            ExcludedInterval(
                started_at=clipped_start,
                ended_at=clipped_end,
                status=segment.status,
                video_record_id=segment.video_record_id,
                detail=segment.detail,
            )
        )
    return RecordingVerification(
        overall=_aggregate(segments, gaps),
        segments=tuple(segments),
        missing_intervals=gaps,
        excluded_intervals=tuple(excluded),
        eligible=tuple(eligible),
        work_dir=directory,
    )


def _verify_record(
    record: VideoRecord,
    *,
    camera_id: UUID,
    directory: Path,
    read_anchor: ReadAnchor,
    fetch_file: FetchFile,
    hash_file: HashFile,
) -> tuple[SegmentVerification, Path | None]:
    started_at = _as_utc(record.started_at)
    chain_started = time.perf_counter()
    try:
        anchored = read_anchor(camera_id, started_at)
    except ChainAnchorError as exc:
        log_playback_step(
            "blockchain",
            chain_started,
            record_id=record.id,
            outcome="error",
        )
        if _anchor_missing(exc):
            return _outcome(record, "missing", _MISSING_ANCHOR), None
        logger.warning(
            "Blockchain read failed for camera %s segment %s: %s",
            camera_id,
            record.id,
            exc,
        )
        return _outcome(record, "failed", _FAILED_CHAIN), None
    except Exception as exc:
        log_playback_step(
            "blockchain",
            chain_started,
            record_id=record.id,
            outcome="error",
        )
        logger.warning(
            "Blockchain read failed for camera %s segment %s: %s",
            camera_id,
            record.id,
            exc,
        )
        return _outcome(record, "failed", _FAILED_CHAIN), None

    log_playback_step(
        "blockchain",
        chain_started,
        record_id=record.id,
        outcome="ok",
    )

    if not _metadata_matches(record, anchored, camera_id=camera_id):
        return _outcome(record, "tampered", _TAMPERED_METADATA), None

    path = directory / f"{record.id}.mp4"
    download_started = time.perf_counter()
    try:
        fetch_file(record.ipfs_cid, path)
    except RecordingDownloadError as exc:
        log_playback_step(
            "ipfs_download",
            download_started,
            record_id=record.id,
            outcome="error",
            bytes=0,
        )
        _remove_file(path)
        logger.warning(
            "IPFS retrieval failed for segment %s: %s",
            record.id,
            exc,
        )
        return _outcome(record, "unavailable", _UNAVAILABLE), None
    except Exception as exc:
        log_playback_step(
            "ipfs_download",
            download_started,
            record_id=record.id,
            outcome="error",
            bytes=0,
        )
        _remove_file(path)
        logger.warning(
            "IPFS retrieval failed for segment %s: %s",
            record.id,
            exc,
        )
        return _outcome(record, "unavailable", _UNAVAILABLE), None

    log_playback_step(
        "ipfs_download",
        download_started,
        record_id=record.id,
        outcome="ok",
        bytes=path.stat().st_size if path.is_file() else 0,
    )

    hash_started = time.perf_counter()
    try:
        digest = hash_file(path)
    except Exception as exc:
        log_playback_step(
            "sha256",
            hash_started,
            record_id=record.id,
            outcome="error",
        )
        _remove_file(path)
        logger.warning("Could not hash segment %s: %s", record.id, exc)
        return _outcome(record, "failed", _FAILED_HASH), None

    log_playback_step(
        "sha256",
        hash_started,
        record_id=record.id,
        outcome="ok",
    )

    if not _same_hash(digest, anchored.segment_hash):
        _remove_file(path)
        return _outcome(record, "tampered", _TAMPERED_FILE), None

    return _outcome(record, "verified", _VERIFIED), path


def _metadata_matches(
    record: VideoRecord,
    anchored: SegmentAnchor,
    *,
    camera_id: UUID,
) -> bool:
    try:
        times_match = unix_uint64(anchored.started_at) == unix_uint64(
            record.started_at
        ) and unix_uint64(anchored.ended_at) == unix_uint64(record.ended_at)
    except ChainAnchorError:
        return False
    return (
        anchored.camera_id == camera_id
        and anchored.camera_id == record.camera_id
        and times_match
        and _same_cid(record.ipfs_cid, anchored.cid)
        and _same_hash(record.segment_hash, anchored.segment_hash)
    )


def _overlapping_records(
    db: Session,
    camera_id: UUID,
    window_start: datetime,
    window_end: datetime,
) -> list[VideoRecord]:
    return list(
        db.execute(
            select(VideoRecord)
            .where(
                VideoRecord.camera_id == camera_id,
                VideoRecord.ended_at > window_start,
                VideoRecord.started_at < window_end,
            )
            .order_by(VideoRecord.started_at.asc())
        )
        .scalars()
        .all()
    )


def _uncovered_intervals(
    window_start: datetime,
    window_end: datetime,
    records: list[VideoRecord],
) -> list[tuple[datetime, datetime]]:
    covered: list[tuple[datetime, datetime]] = []
    for record in records:
        clipped = _clip(
            _as_utc(record.started_at),
            _as_utc(record.ended_at),
            window_start,
            window_end,
        )
        if clipped is not None:
            covered.append(clipped)
    covered.sort()
    merged: list[tuple[datetime, datetime]] = []
    for start, end in covered:
        if not merged or _is_uncovered_gap(merged[-1][1], start):
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))

    gaps: list[tuple[datetime, datetime]] = []
    cursor = window_start
    for start, end in merged:
        if _is_uncovered_gap(cursor, start):
            gaps.append((cursor, start))
        cursor = max(cursor, end)
    if _is_uncovered_gap(cursor, window_end):
        gaps.append((cursor, window_end))
    return gaps


def _is_uncovered_gap(left: datetime, right: datetime) -> bool:
    """True when ``right`` starts at least 1 millisecond after ``left``."""
    return right - left >= _MIN_UNCOVERED_GAP


def _clip(
    started_at: datetime,
    ended_at: datetime,
    window_start: datetime,
    window_end: datetime,
) -> tuple[datetime, datetime] | None:
    start = max(started_at, window_start)
    end = min(ended_at, window_end)
    if end <= start:
        return None
    return start, end


def _aggregate(
    segments: list[SegmentVerification],
    gaps: tuple[MissingInterval, ...],
) -> VerifyStatus:
    statuses = {segment.status for segment in segments}
    for status in _WORST_FIRST:
        if status in statuses:
            return status
    if gaps or not segments:
        return "missing"
    return "verified"


def _outcome(
    record: VideoRecord,
    status: VerifyStatus,
    detail: str,
) -> SegmentVerification:
    return SegmentVerification(
        video_record_id=record.id,
        started_at=_as_utc(record.started_at),
        ended_at=_as_utc(record.ended_at),
        status=status,
        detail=detail,
        ipfs_cid=record.ipfs_cid,
        segment_hash=record.segment_hash,
    )


def _anchor_missing(exc: ChainAnchorError) -> bool:
    return isinstance(exc, ChainAnchorNotFoundError)


def _same_cid(stored: str, anchored: str) -> bool:
    return stored.strip() == anchored.strip()


def _same_hash(left: str, right: str) -> bool:
    return _normalize_hash(left) == _normalize_hash(right) and bool(
        _normalize_hash(left)
    )


def _normalize_hash(value: str) -> str:
    return value.strip().lower().removeprefix("0x")


def _remove_file(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.warning("Could not remove unverified file %s", path)


def _make_work_dir() -> Path:
    root = resolve_temp_dir() / "verify"
    root.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="verify-", dir=root))


def _as_utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)
