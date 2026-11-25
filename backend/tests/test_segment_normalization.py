"""Playback timestamp normalization before IPFS upload and chain anchor."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.camera import Camera
from app.models.user import User
from app.models.video_record import VideoRecord
from app.security.password import hash_password
from app.services.chain_anchor import (
    ChainAnchorNotFoundError,
    SegmentAnchor,
    SegmentAnchorRequest,
)
from app.services.ingest_segment_processor import (
    IngestPermanentError,
    SegmentNormalizationError,
    _require_playable_copy,
    normalization_ffmpeg_command,
    normalize_segment_media,
    process_ingest_segment,
)
from app.services.segment_staging import staging_dir_for_camera

import app.models as _models  # noqa: F401

CAMERA_ID = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
CID = "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi"
TX = "0x" + "ab" * 32
NORMALIZED = b"normalized-mp4-bytes"


def _box(box_type: bytes, payload: bytes) -> bytes:
    size = 8 + len(payload)
    return size.to_bytes(4, "big") + box_type + payload


def _minimal_mp4() -> bytes:
    ftyp = _box(b"ftyp", b"isom" + (0).to_bytes(4, "big") + b"isom")
    moov = _box(b"moov", b"")
    return ftyp + moov


@pytest.fixture
def session_factory() -> sessionmaker:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = factory()
    user = User(email="norm@example.com", password_hash=hash_password("password12"))
    db.add(user)
    db.flush()
    db.add(
        Camera(
            id=CAMERA_ID,
            user_id=user.id,
            name="Gate",
            stream_url="rtsp://192.0.2.50/live",
        )
    )
    db.commit()
    db.close()
    return factory


def _segment(tmp_path: Path) -> Path:
    staging = staging_dir_for_camera(CAMERA_ID, tmp_path)
    staging.mkdir()
    path = staging / f"{CAMERA_ID}_20260824T120000Z.mp4"
    path.write_bytes(_minimal_mp4())
    return path


def _closed_timeline(path: Path, *, start: float, end: float) -> None:
    csv_path = path.parent / "segments_run.csv"
    csv_path.write_text(f"{path.name},{start:.6f},{end:.6f}\n")
    (path.parent / "segments_run.csv.closed").write_text("")


def _not_anchored(_camera_id: UUID, _started_at: datetime) -> SegmentAnchor:
    raise ChainAnchorNotFoundError()


def _write_normalized(source: Path, **_kwargs: object) -> Path:
    destination = source.parent / ".segment-normalized" / source.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(NORMALIZED)
    return destination


def test_normalization_command_copies_every_stream() -> None:
    source = Path("/tmp/source.mp4")
    destination = Path("/tmp/out.mp4")
    command = normalization_ffmpeg_command(source, destination)
    assert command[command.index("-map") + 1] == "0"
    assert command[command.index("-c") + 1] == "copy"
    assert command[command.index("-avoid_negative_ts") + 1] == "make_zero"
    assert "0:v:0" not in command
    assert "-an" not in command


def test_normalize_rejects_failed_remux_and_removes_the_copy(tmp_path: Path) -> None:
    source = _segment(tmp_path)
    original = source.read_bytes()

    class _Result:
        returncode = 1
        stderr = "mux failed"

    with patch(
        "app.services.ingest_segment_processor.subprocess.run",
        return_value=_Result(),
    ):
        with pytest.raises(SegmentNormalizationError, match="mux failed"):
            normalize_segment_media(
                source,
                file_start_time=4.779533,
                file_duration=60.0,
            )
    assert source.read_bytes() == original
    assert not (source.parent / ".segment-normalized").exists()


def test_playable_copy_requires_zero_start_same_duration_and_streams(
    tmp_path: Path,
) -> None:
    source = _segment(tmp_path)
    destination = source.parent / ".segment-normalized" / source.name
    destination.parent.mkdir()
    destination.write_bytes(b"copy")

    def accept(path: Path, **_kwargs: object) -> tuple[float, float]:
        if path == destination:
            return (0.0, 60.0)
        return (4.779533, 60.0)

    with (
        patch(
            "app.services.ingest_segment_processor.probe_video_timing",
            side_effect=accept,
        ),
        patch(
            "app.services.ingest_segment_processor._playback_stream_counts",
            return_value=(1, 1),
        ),
    ):
        _require_playable_copy(
            source,
            destination,
            file_duration=60.0,
            ffprobe_executable="ffprobe",
        )

    with (
        patch(
            "app.services.ingest_segment_processor.probe_video_timing",
            return_value=(0.0, 55.0),
        ),
        patch(
            "app.services.ingest_segment_processor._playback_stream_counts",
            return_value=(1, 1),
        ),
    ):
        with pytest.raises(SegmentNormalizationError, match="duration"):
            _require_playable_copy(
                source,
                destination,
                file_duration=60.0,
                ffprobe_executable="ffprobe",
            )

    def counts(path: Path, **_kwargs: object) -> tuple[int, int]:
        if path == source:
            return (1, 1)
        return (1, 0)

    with (
        patch(
            "app.services.ingest_segment_processor.probe_video_timing",
            return_value=(0.0, 60.0),
        ),
        patch(
            "app.services.ingest_segment_processor._playback_stream_counts",
            side_effect=counts,
        ),
    ):
        with pytest.raises(SegmentNormalizationError, match="audio"):
            _require_playable_copy(
                source,
                destination,
                file_duration=60.0,
                ffprobe_executable="ffprobe",
            )


def test_nonzero_start_publishes_normalized_bytes_and_keeps_utc_window(
    tmp_path: Path,
    session_factory: sessionmaker,
) -> None:
    path = _segment(tmp_path)
    original = path.read_bytes()
    _closed_timeline(path, start=0.0, end=64.779533)
    uploaded: list[bytes] = []
    anchored: list[SegmentAnchorRequest] = []

    def upload(candidate: Path) -> str:
        uploaded.append(candidate.read_bytes())
        return CID

    def anchor(request: SegmentAnchorRequest) -> str:
        anchored.append(request)
        return TX

    with (
        patch(
            "app.services.ingest_segment_processor.probe_video_timing",
            return_value=(4.779533, 60.0),
        ),
        patch(
            "app.services.ingest_segment_processor.normalize_segment_media",
            side_effect=_write_normalized,
        ),
    ):
        ok = process_ingest_segment(
            path,
            duration_seconds=60,
            session_factory=session_factory,
            upload=upload,
            send_anchor=anchor,
            read_anchor=_not_anchored,
        )

    assert ok is True
    assert uploaded == [NORMALIZED]
    assert path.read_bytes() == original
    assert not (path.parent / ".segment-normalized").exists()
    digest = hashlib.sha256(NORMALIZED).hexdigest()
    assert anchored[0].segment_hash == digest
    span = (anchored[0].ended_at - anchored[0].started_at).total_seconds()
    assert span == pytest.approx(60.0)
    opened = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    assert anchored[0].started_at == opened
    db: Session = session_factory()
    try:
        row = db.query(VideoRecord).one()
        assert row.segment_hash == digest
        assert row.ipfs_cid == CID
    finally:
        db.close()


def test_contiguous_window_uses_source_start_before_normalization(
    tmp_path: Path,
    session_factory: sessionmaker,
) -> None:
    path = _segment(tmp_path)
    second = f"{CAMERA_ID}_20260824T120008Z.mp4"
    csv_path = path.parent / "segments_run.csv"
    csv_path.write_text(f"{path.name},0.000000,8.080000\n{second},8.080000,13.080000\n")
    anchored: list[SegmentAnchorRequest] = []

    with (
        patch(
            "app.services.ingest_segment_processor.probe_video_timing",
            return_value=(3.08, 5.0),
        ),
        patch(
            "app.services.ingest_segment_processor.normalize_segment_media",
            side_effect=_write_normalized,
        ),
    ):
        ok = process_ingest_segment(
            path,
            duration_seconds=60,
            session_factory=session_factory,
            upload=lambda _candidate: CID,
            send_anchor=lambda request: anchored.append(request) or TX,
            read_anchor=_not_anchored,
        )

    assert ok is True
    reference = datetime(2026, 8, 24, 12, 0, 8, tzinfo=timezone.utc)
    offset = (anchored[0].started_at - reference).total_seconds()
    assert offset == pytest.approx(3.08 - 8.08)
    span = (anchored[0].ended_at - anchored[0].started_at).total_seconds()
    assert span == pytest.approx(5.0)
    assert anchored[0].segment_hash == hashlib.sha256(NORMALIZED).hexdigest()


def test_duration_mismatch_does_not_publish(
    tmp_path: Path,
    session_factory: sessionmaker,
) -> None:
    path = _segment(tmp_path)
    original = path.read_bytes()
    _closed_timeline(path, start=0.0, end=64.779533)
    uploads: list[Path] = []

    def reject(source: Path, **_kwargs: object) -> Path:
        raise SegmentNormalizationError(
            "Normalized duration 55.000000 differs from source duration 60.000000"
        )

    with (
        patch(
            "app.services.ingest_segment_processor.probe_video_timing",
            return_value=(4.779533, 60.0),
        ),
        patch(
            "app.services.ingest_segment_processor.normalize_segment_media",
            side_effect=reject,
        ),
    ):
        ok = process_ingest_segment(
            path,
            session_factory=session_factory,
            upload=lambda candidate: uploads.append(candidate) or CID,
            send_anchor=lambda _request: TX,
            read_anchor=_not_anchored,
        )
    assert ok is False
    assert uploads == []
    assert path.read_bytes() == original
    assert not (path.parent / ".segment-normalized").exists()


def test_existing_database_row_is_not_reanchored_from_a_normalized_hash(
    tmp_path: Path,
    session_factory: sessionmaker,
) -> None:
    path = _segment(tmp_path)
    _closed_timeline(path, start=0.0, end=64.779533)
    started = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    stored_hash = "ab" * 32
    db = session_factory()
    try:
        db.add(
            VideoRecord(
                id=uuid4(),
                camera_id=CAMERA_ID,
                started_at=started,
                ended_at=started + timedelta(seconds=60),
                ipfs_cid=CID,
                segment_hash=stored_hash,
                tx_hash=TX,
            )
        )
        db.commit()
    finally:
        db.close()
    uploads: list[Path] = []

    def found(_camera_id: UUID, _started_at: datetime) -> SegmentAnchor:
        return SegmentAnchor(
            camera_id=CAMERA_ID,
            started_at=started,
            ended_at=started + timedelta(seconds=60),
            cid=CID,
            segment_hash=stored_hash,
        )

    with (
        patch(
            "app.services.ingest_segment_processor.probe_video_timing",
            return_value=(4.779533, 60.0),
        ),
        patch(
            "app.services.ingest_segment_processor.normalize_segment_media",
            side_effect=AssertionError("historical row must not be remuxed"),
        ),
    ):
        ok = process_ingest_segment(
            path,
            session_factory=session_factory,
            upload=lambda candidate: uploads.append(candidate) or CID,
            send_anchor=lambda _request: TX,
            read_anchor=found,
        )
    assert ok is True
    assert uploads == []
    db = session_factory()
    try:
        row = db.query(VideoRecord).one()
        assert row.segment_hash == stored_hash
        assert row.ipfs_cid == CID
    finally:
        db.close()


def test_existing_chain_anchor_rejects_a_different_normalized_hash(
    tmp_path: Path,
    session_factory: sessionmaker,
) -> None:
    path = _segment(tmp_path)
    _closed_timeline(path, start=0.0, end=64.779533)
    started = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    uploads: list[Path] = []

    def occupied(_camera_id: UUID, _started_at: datetime) -> SegmentAnchor:
        return SegmentAnchor(
            camera_id=CAMERA_ID,
            started_at=started,
            ended_at=started + timedelta(seconds=60),
            cid="bafyhistorical",
            segment_hash="cd" * 32,
        )

    with (
        patch(
            "app.services.ingest_segment_processor.probe_video_timing",
            return_value=(4.779533, 60.0),
        ),
        patch(
            "app.services.ingest_segment_processor.normalize_segment_media",
            side_effect=_write_normalized,
        ),
    ):
        with pytest.raises(IngestPermanentError, match="conflicts"):
            process_ingest_segment(
                path,
                session_factory=session_factory,
                upload=lambda candidate: uploads.append(candidate) or CID,
                send_anchor=lambda _request: TX,
                read_anchor=occupied,
            )
    assert uploads == []
    assert path.exists()
    assert not (path.parent / ".segment-normalized").exists()


def test_retry_after_anchor_reuses_the_same_normalized_hash(
    tmp_path: Path,
    session_factory: sessionmaker,
) -> None:
    path = _segment(tmp_path)
    _closed_timeline(path, start=0.0, end=64.779533)
    digest = hashlib.sha256(NORMALIZED).hexdigest()
    started = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    ended = started + timedelta(seconds=60)
    uploads: list[bytes] = []
    sends: list[SegmentAnchorRequest] = []
    anchored = {"done": False}

    def upload(candidate: Path) -> str:
        uploads.append(candidate.read_bytes())
        return CID

    def send(request: SegmentAnchorRequest) -> str:
        sends.append(request)
        anchored["done"] = True
        return TX

    def read(_camera_id: UUID, _started_at: datetime) -> SegmentAnchor:
        if not anchored["done"]:
            raise ChainAnchorNotFoundError()
        return SegmentAnchor(
            camera_id=CAMERA_ID,
            started_at=started,
            ended_at=ended,
            cid=CID,
            segment_hash=digest,
        )

    with (
        patch(
            "app.services.ingest_segment_processor.probe_video_timing",
            return_value=(4.779533, 60.0),
        ),
        patch(
            "app.services.ingest_segment_processor.normalize_segment_media",
            side_effect=_write_normalized,
        ),
        patch(
            "app.services.ingest_segment_processor.persist_video_record",
            side_effect=RuntimeError("database unavailable"),
        ),
    ):
        first = process_ingest_segment(
            path,
            session_factory=session_factory,
            upload=upload,
            send_anchor=send,
            read_anchor=read,
        )
    assert first is False
    assert uploads == [NORMALIZED]
    assert sends[0].segment_hash == digest
    assert path.exists()
    assert not (path.parent / ".segment-normalized").exists()

    with (
        patch(
            "app.services.ingest_segment_processor.probe_video_timing",
            return_value=(4.779533, 60.0),
        ),
        patch(
            "app.services.ingest_segment_processor.normalize_segment_media",
            side_effect=_write_normalized,
        ),
    ):
        second = process_ingest_segment(
            path,
            session_factory=session_factory,
            upload=upload,
            send_anchor=send,
            read_anchor=read,
        )
    assert second is True
    assert uploads == [NORMALIZED]
    assert len(sends) == 1
    db = session_factory()
    try:
        row = db.query(VideoRecord).one()
        assert row.segment_hash == digest
        assert row.ipfs_cid == CID
        assert row.tx_hash is None
    finally:
        db.close()
