"""Tests for ingest Pinata + chain + DB processing (Slice D)."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.camera import Camera
from app.models.user import User
from app.models.video_record import VideoRecord
from app.security.password import hash_password
from app.services.camera_ingest import (
    CameraIngestConfig,
    integrity_worker_config_for_ingest,
)
from app.services.chain_anchor import (
    ChainAnchorError,
    SegmentAnchor,
    SegmentAnchorRequest,
)
from app.services.chunk_processing_worker import (
    ChunkProcessingWorker,
    ChunkProcessingWorkerConfig,
)
from app.services.ingest_segment_processor import (
    IngestPermanentError,
    process_ingest_segment,
)
from app.services.pinata_ipfs import PinataUploadError
from app.services.segment_identity import camera_segment_pattern
from app.services.segment_integrity import SegmentIntegrityResult, sha256_file
from app.services.segment_timeline import (
    SegmentTimelineNotReady,
    SegmentTimelinePermanentError,
)
from app.services.segment_staging import (
    keep_staged_until_processing_succeeds,
    staging_dir_for_camera,
)

import app.models as _models  # noqa: F401

CAMERA_ID = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
CID = "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi"
TX = "0x" + "ab" * 32


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
    user = User(email="proc@example.com", password_hash=hash_password("password12"))
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


def _not_anchored(_camera_id: UUID, _started_at: datetime) -> SegmentAnchor:
    raise ChainAnchorError("AnchorNotFound")


def _closed_timeline(path: Path, *, start: float, duration: float) -> None:
    end = start + duration
    csv_path = path.parent / "segments_run.csv"
    csv_path.write_text(f"{path.name},{start:.6f},{end:.6f}\n")
    (path.parent / "segments_run.csv.closed").write_text("")


def _as_utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def test_process_success_saves_row_and_can_delete(
    tmp_path: Path, session_factory: sessionmaker
) -> None:
    path = _segment(tmp_path)
    _closed_timeline(path, start=0.0, duration=60.0)
    with patch(
        "app.services.ingest_segment_processor.probe_video_timing",
        return_value=(0.0, 60.0),
    ):
        ok = process_ingest_segment(
            path,
            duration_seconds=60,
            session_factory=session_factory,
            upload=lambda _p: CID,
            send_anchor=lambda _req: TX,
            read_anchor=_not_anchored,
        )
    assert ok is True
    db: Session = session_factory()
    try:
        row = db.query(VideoRecord).one()
        assert row.camera_id == CAMERA_ID
        assert row.ipfs_cid == CID
        assert row.tx_hash == TX
        assert len(row.segment_hash) == 64
    finally:
        db.close()


def test_process_keeps_going_false_on_ipfs_failure(
    tmp_path: Path, session_factory: sessionmaker
) -> None:
    path = _segment(tmp_path)
    _closed_timeline(path, start=0.0, duration=60.0)

    def fail_upload(_p: Path) -> str:
        raise PinataUploadError("no pinata")

    with patch(
        "app.services.ingest_segment_processor.probe_video_timing",
        return_value=(0.0, 60.0),
    ):
        assert (
            process_ingest_segment(
                path,
                session_factory=session_factory,
                upload=fail_upload,
                send_anchor=lambda _req: TX,
                read_anchor=_not_anchored,
            )
            is False
        )
    db = session_factory()
    try:
        assert db.query(VideoRecord).count() == 0
    finally:
        db.close()
    assert path.exists()


def test_process_keeps_file_on_anchor_failure(
    tmp_path: Path, session_factory: sessionmaker
) -> None:
    path = _segment(tmp_path)
    _closed_timeline(path, start=0.0, duration=60.0)

    def fail_anchor(_req: SegmentAnchorRequest) -> str:
        raise ChainAnchorError("RPC timeout")

    with patch(
        "app.services.ingest_segment_processor.probe_video_timing",
        return_value=(0.0, 60.0),
    ):
        assert (
            process_ingest_segment(
                path,
                session_factory=session_factory,
                upload=lambda _p: CID,
                send_anchor=fail_anchor,
                read_anchor=_not_anchored,
            )
            is False
        )
    db = session_factory()
    try:
        assert db.query(VideoRecord).count() == 0
    finally:
        db.close()


def test_ingest_worker_deletes_after_mocked_success(
    tmp_path: Path, session_factory: sessionmaker
) -> None:
    path = _segment(tmp_path)
    _closed_timeline(path, start=0.0, duration=60.0)
    config = CameraIngestConfig(
        camera_id=CAMERA_ID,
        stream_url="rtsp://192.0.2.50/live",
        temp_dir=tmp_path,
    )
    worker_config = integrity_worker_config_for_ingest(
        config, session_factory=session_factory
    )
    worker_config.stable_delay_seconds = 0
    worker_config.integrity_check = lambda p: SegmentIntegrityResult(
        ok=True, path=p, sha256="abc", size_bytes=1
    )
    worker_config.processor = lambda p: process_ingest_segment(
        p,
        duration_seconds=60,
        session_factory=session_factory,
        upload=lambda _p: CID,
        send_anchor=lambda _req: TX,
        read_anchor=_not_anchored,
    )

    worker = ChunkProcessingWorker(worker_config)

    with patch(
        "app.services.ingest_segment_processor.probe_video_timing",
        return_value=(0.0, 60.0),
    ):
        assert worker.process_all_blocking() == 1

    assert not path.exists()


def test_ingest_worker_config_deletes_on_processor_success(tmp_path: Path) -> None:
    config = CameraIngestConfig(
        camera_id=CAMERA_ID,
        stream_url="rtsp://192.0.2.50/live",
        temp_dir=tmp_path,
    )
    worker_config = integrity_worker_config_for_ingest(config)
    assert worker_config.delete_on_success is True
    assert worker_config.processor is not keep_staged_until_processing_succeeds
    assert worker_config.segment_pattern == camera_segment_pattern(CAMERA_ID)


def test_partial_segment_uses_actual_duration(
    tmp_path: Path,
    session_factory: sessionmaker,
) -> None:
    path = _segment(tmp_path)
    _closed_timeline(path, start=0.0, duration=53.88)
    anchored_requests: list[SegmentAnchorRequest] = []

    def fake_anchor(request: SegmentAnchorRequest) -> str:
        anchored_requests.append(request)
        return TX

    with patch(
        "app.services.ingest_segment_processor.probe_video_timing",
        return_value=(0.0, 53.88),
    ):
        ok = process_ingest_segment(
            path,
            duration_seconds=60,
            session_factory=session_factory,
            upload=lambda _p: CID,
            send_anchor=fake_anchor,
            read_anchor=_not_anchored,
        )

    assert ok is True

    expected_start = datetime(2026, 8, 24, 12, 0, 0, tzinfo=timezone.utc)
    assert len(anchored_requests) == 1
    assert anchored_requests[0].started_at == expected_start
    span = (
        anchored_requests[0].ended_at - anchored_requests[0].started_at
    ).total_seconds()
    assert span == pytest.approx(53.88)

    db = session_factory()
    try:
        row = db.query(VideoRecord).one()
        assert _as_utc(row.started_at) == expected_start
        stored = (_as_utc(row.ended_at) - expected_start).total_seconds()
        assert stored == pytest.approx(53.88)
        assert _as_utc(row.ended_at) == anchored_requests[0].ended_at
    finally:
        db.close()


def test_segment_slightly_over_60_seconds_is_accepted(
    tmp_path: Path,
    session_factory: sessionmaker,
) -> None:
    path = _segment(tmp_path)
    _closed_timeline(path, start=0.0, duration=60.04)
    anchored_requests: list[SegmentAnchorRequest] = []

    def fake_anchor(request: SegmentAnchorRequest) -> str:
        anchored_requests.append(request)
        return TX

    with patch(
        "app.services.ingest_segment_processor.probe_video_timing",
        return_value=(0.0, 60.04),
    ):
        ok = process_ingest_segment(
            path,
            duration_seconds=60,
            session_factory=session_factory,
            upload=lambda _p: CID,
            send_anchor=fake_anchor,
            read_anchor=_not_anchored,
        )

    assert ok is True
    assert len(anchored_requests) == 1


def test_keyframe_overrun_is_stored_from_the_timeline(
    tmp_path: Path,
    session_factory: sessionmaker,
) -> None:
    path = _segment(tmp_path)
    _closed_timeline(path, start=2.24, duration=20.0)
    anchored_requests: list[SegmentAnchorRequest] = []

    def fake_anchor(request: SegmentAnchorRequest) -> str:
        anchored_requests.append(request)
        return TX

    with patch(
        "app.services.ingest_segment_processor.probe_video_timing",
        return_value=(2.24, 20.0),
    ):
        ok = process_ingest_segment(
            path,
            duration_seconds=15,
            session_factory=session_factory,
            upload=lambda _p: CID,
            send_anchor=fake_anchor,
            read_anchor=_not_anchored,
        )

    assert ok is True
    span = (
        anchored_requests[0].ended_at - anchored_requests[0].started_at
    ).total_seconds()
    assert span == pytest.approx(20.0)


def test_second_segment_reference_maps_utc_window(
    tmp_path: Path,
    session_factory: sessionmaker,
) -> None:
    path = _segment(tmp_path)
    second = f"{CAMERA_ID}_20260824T120008Z.mp4"
    csv_path = path.parent / "segments_run.csv"
    csv_path.write_text(
        f"{path.name},0.000000,8.080000\n{second},8.080000,13.080000\n"
    )
    anchored: list[SegmentAnchorRequest] = []

    def fake_anchor(request: SegmentAnchorRequest) -> str:
        anchored.append(request)
        return TX

    with patch(
        "app.services.ingest_segment_processor.probe_video_timing",
        return_value=(3.08, 5.0),
    ):
        ok = process_ingest_segment(
            path,
            duration_seconds=60,
            session_factory=session_factory,
            upload=lambda _p: CID,
            send_anchor=fake_anchor,
            read_anchor=_not_anchored,
        )

    assert ok is True
    reference = datetime(2026, 8, 24, 12, 0, 8, tzinfo=timezone.utc)
    offset = (anchored[0].started_at - reference).total_seconds()
    assert offset == pytest.approx(3.08 - 8.08)
    span = (anchored[0].ended_at - anchored[0].started_at).total_seconds()
    assert span == pytest.approx(5.0)
    db = session_factory()
    try:
        row = db.query(VideoRecord).one()
        assert _as_utc(row.started_at) == anchored[0].started_at
        assert _as_utc(row.ended_at) == anchored[0].ended_at
    finally:
        db.close()


def test_timeline_not_ready_is_retried_without_deleting(
    tmp_path: Path,
    session_factory: sessionmaker,
) -> None:
    path = _segment(tmp_path)
    calls = {"n": 0}

    def processor(candidate: Path) -> bool:
        calls["n"] += 1
        return process_ingest_segment(
            candidate,
            session_factory=session_factory,
            upload=lambda _p: CID,
            send_anchor=lambda _req: TX,
            read_anchor=_not_anchored,
        )

    worker = ChunkProcessingWorker(
        ChunkProcessingWorkerConfig(
            temp_dir=path.parent,
            stable_delay_seconds=0,
            segment_pattern=camera_segment_pattern(CAMERA_ID),
            processor=processor,
        ),
    )
    with patch(
        "app.services.ingest_segment_processor.probe_video_timing",
        return_value=(0.0, 60.0),
    ):
        with pytest.raises(SegmentTimelineNotReady):
            process_ingest_segment(
                path,
                session_factory=session_factory,
                upload=lambda _p: CID,
                send_anchor=lambda _req: TX,
                read_anchor=_not_anchored,
            )
        assert worker.process_all_blocking() == 0
    assert path.exists()
    assert not (path.parent / f"{path.name}.invalid").exists()
    assert calls["n"] == 1
    db = session_factory()
    try:
        assert db.query(VideoRecord).count() == 0
    finally:
        db.close()


def test_permanent_timeline_error_is_not_processed_again(
    tmp_path: Path,
    session_factory: sessionmaker,
) -> None:
    path = _segment(tmp_path)
    csv_path = path.parent / "segments_run.csv"
    csv_path.write_text("other.mp4,0.000000,60.000000\n")
    (path.parent / "segments_run.csv.closed").write_text("")
    calls = {"n": 0}

    def processor(candidate: Path) -> bool:
        calls["n"] += 1
        return process_ingest_segment(
            candidate,
            session_factory=session_factory,
            upload=lambda _p: CID,
            send_anchor=lambda _req: TX,
            read_anchor=_not_anchored,
        )

    worker = ChunkProcessingWorker(
        ChunkProcessingWorkerConfig(
            temp_dir=path.parent,
            stable_delay_seconds=0,
            segment_pattern=camera_segment_pattern(CAMERA_ID),
            processor=processor,
        ),
    )
    with patch(
        "app.services.ingest_segment_processor.probe_video_timing",
        return_value=(0.0, 60.0),
    ):
        with pytest.raises(SegmentTimelinePermanentError):
            process_ingest_segment(
                path,
                session_factory=session_factory,
                upload=lambda _p: CID,
                send_anchor=lambda _req: TX,
                read_anchor=_not_anchored,
            )
        assert worker.process_all_blocking() == 0
        assert worker.process_all_blocking() == 0
    assert path.exists()
    assert (path.parent / f"{path.name}.invalid").is_file()
    assert calls["n"] == 1


def test_collapsed_chain_window_is_permanent(
    tmp_path: Path,
    session_factory: sessionmaker,
) -> None:
    path = _segment(tmp_path)
    _closed_timeline(path, start=0.2, duration=0.3)
    uploads: list[Path] = []

    with patch(
        "app.services.ingest_segment_processor.probe_video_timing",
        return_value=(0.2, 0.3),
    ):
        with pytest.raises(IngestPermanentError, match="time window"):
            process_ingest_segment(
                path,
                session_factory=session_factory,
                upload=lambda candidate: uploads.append(candidate) or CID,
                send_anchor=lambda _req: TX,
                read_anchor=_not_anchored,
            )
    assert uploads == []
    assert path.exists()


def test_same_second_database_row_is_not_overwritten(
    tmp_path: Path,
    session_factory: sessionmaker,
) -> None:
    path = _segment(tmp_path)
    _closed_timeline(path, start=0.0, duration=60.0)
    started = datetime(2026, 8, 24, 12, 0, 0, tzinfo=timezone.utc)
    neighbor = started + timedelta(milliseconds=200)
    db = session_factory()
    try:
        db.add(
            VideoRecord(
                id=uuid4(),
                camera_id=CAMERA_ID,
                started_at=neighbor,
                ended_at=neighbor + timedelta(seconds=60),
                ipfs_cid="bafyneighbor",
                segment_hash="11" * 32,
                tx_hash="0x" + "11" * 32,
            )
        )
        db.commit()
    finally:
        db.close()
    uploads: list[Path] = []
    with patch(
        "app.services.ingest_segment_processor.probe_video_timing",
        return_value=(0.0, 60.0),
    ):
        with pytest.raises(IngestPermanentError, match="occupies"):
            process_ingest_segment(
                path,
                session_factory=session_factory,
                upload=lambda candidate: uploads.append(candidate) or CID,
                send_anchor=lambda _req: TX,
                read_anchor=_not_anchored,
            )
    assert uploads == []
    db = session_factory()
    try:
        row = db.query(VideoRecord).one()
        assert row.ipfs_cid == "bafyneighbor"
        assert row.segment_hash == "11" * 32
        assert _as_utc(row.started_at) == neighbor
    finally:
        db.close()


def test_conflicting_chain_anchor_is_not_replaced(
    tmp_path: Path,
    session_factory: sessionmaker,
) -> None:
    path = _segment(tmp_path)
    _closed_timeline(path, start=0.0, duration=60.0)
    started = datetime(2026, 8, 24, 12, 0, 0, tzinfo=timezone.utc)
    sends: list[SegmentAnchorRequest] = []
    calls = {"n": 0}

    def occupied(_camera_id: UUID, _started_at: datetime) -> SegmentAnchor:
        return SegmentAnchor(
            camera_id=CAMERA_ID,
            started_at=started,
            ended_at=started + timedelta(seconds=60),
            cid="bafyother",
            segment_hash="22" * 32,
        )

    with patch(
        "app.services.ingest_segment_processor.probe_video_timing",
        return_value=(0.0, 60.0),
    ):
        with pytest.raises(IngestPermanentError, match="conflicts"):
            process_ingest_segment(
                path,
                session_factory=session_factory,
                upload=lambda _p: CID,
                send_anchor=lambda request: sends.append(request) or TX,
                read_anchor=occupied,
            )

        def processor(candidate: Path) -> bool:
            calls["n"] += 1
            return process_ingest_segment(
                candidate,
                session_factory=session_factory,
                upload=lambda _p: CID,
                send_anchor=lambda request: sends.append(request) or TX,
                read_anchor=occupied,
            )

        worker = ChunkProcessingWorker(
            ChunkProcessingWorkerConfig(
                temp_dir=path.parent,
                stable_delay_seconds=0,
                segment_pattern=camera_segment_pattern(CAMERA_ID),
                processor=processor,
            ),
        )
        assert worker.process_all_blocking() == 0
        assert worker.process_all_blocking() == 0
    assert calls["n"] == 1
    assert (path.parent / f"{path.name}.invalid").is_file()
    assert sends == []
    db = session_factory()
    try:
        assert db.query(VideoRecord).count() == 0
    finally:
        db.close()


def test_matching_chain_anchor_is_saved_without_a_new_transaction(
    tmp_path: Path,
    session_factory: sessionmaker,
) -> None:
    path = _segment(tmp_path)
    _closed_timeline(path, start=0.0, duration=60.0)
    digest = sha256_file(path)
    started = datetime(2026, 8, 24, 12, 0, 0, tzinfo=timezone.utc)
    ended = started + timedelta(seconds=60)
    uploads: list[Path] = []
    sends: list[SegmentAnchorRequest] = []

    def found(_camera_id: UUID, _started_at: datetime) -> SegmentAnchor:
        return SegmentAnchor(
            camera_id=CAMERA_ID,
            started_at=started,
            ended_at=ended,
            cid=CID,
            segment_hash=digest,
        )

    with patch(
        "app.services.ingest_segment_processor.probe_video_timing",
        return_value=(0.0, 60.0),
    ):
        ok = process_ingest_segment(
            path,
            session_factory=session_factory,
            upload=lambda candidate: uploads.append(candidate) or CID,
            send_anchor=lambda request: sends.append(request) or TX,
            read_anchor=found,
        )
    assert ok is True
    assert uploads == []
    assert sends == []
    db = session_factory()
    try:
        row = db.query(VideoRecord).one()
        assert row.ipfs_cid == CID
        assert row.segment_hash == digest
        assert row.tx_hash is None
        assert _as_utc(row.started_at) == started
        assert _as_utc(row.ended_at) == ended
    finally:
        db.close()


def test_already_anchored_race_does_not_create_a_second_record(
    tmp_path: Path,
    session_factory: sessionmaker,
) -> None:
    path = _segment(tmp_path)
    _closed_timeline(path, start=0.0, duration=60.0)
    digest = sha256_file(path)
    started = datetime(2026, 8, 24, 12, 0, 0, tzinfo=timezone.utc)
    ended = started + timedelta(seconds=60)
    reads = {"n": 0}
    sends: list[SegmentAnchorRequest] = []

    def read(_camera_id: UUID, _started_at: datetime) -> SegmentAnchor:
        reads["n"] += 1
        if reads["n"] == 1:
            raise ChainAnchorError("AnchorNotFound")
        return SegmentAnchor(
            camera_id=CAMERA_ID,
            started_at=started,
            ended_at=ended,
            cid=CID,
            segment_hash=digest,
        )

    def send(request: SegmentAnchorRequest) -> str:
        sends.append(request)
        raise ChainAnchorError("AlreadyAnchored")

    with patch(
        "app.services.ingest_segment_processor.probe_video_timing",
        return_value=(0.0, 60.0),
    ):
        ok = process_ingest_segment(
            path,
            session_factory=session_factory,
            upload=lambda _p: CID,
            send_anchor=send,
            read_anchor=read,
        )
        assert ok is True
        ok_again = process_ingest_segment(
            path,
            session_factory=session_factory,
            upload=lambda _p: CID,
            send_anchor=send,
            read_anchor=read,
        )
    assert ok_again is True
    assert len(sends) == 1
    db = session_factory()
    try:
        row = db.query(VideoRecord).one()
        assert row.ipfs_cid == CID
        assert row.segment_hash == digest
        assert row.tx_hash is None
    finally:
        db.close()


def test_retry_does_not_change_an_existing_matching_record(
    tmp_path: Path,
    session_factory: sessionmaker,
) -> None:
    path = _segment(tmp_path)
    _closed_timeline(path, start=0.0, duration=60.0)
    digest = sha256_file(path)
    started = datetime(2026, 8, 24, 12, 0, 0, tzinfo=timezone.utc)
    stored_end = started + timedelta(seconds=54)
    db = session_factory()
    try:
        db.add(
            VideoRecord(
                id=uuid4(),
                camera_id=CAMERA_ID,
                started_at=started,
                ended_at=stored_end,
                ipfs_cid=CID,
                segment_hash=digest,
                tx_hash=TX,
            )
        )
        db.commit()
    finally:
        db.close()
    uploads: list[Path] = []
    sends: list[SegmentAnchorRequest] = []

    def found(_camera_id: UUID, _started_at: datetime) -> SegmentAnchor:
        return SegmentAnchor(
            camera_id=CAMERA_ID,
            started_at=started,
            ended_at=stored_end,
            cid=CID,
            segment_hash=digest,
        )

    with patch(
        "app.services.ingest_segment_processor.probe_video_timing",
        return_value=(0.0, 53.88),
    ):
        ok = process_ingest_segment(
            path,
            session_factory=session_factory,
            upload=lambda candidate: uploads.append(candidate) or CID,
            send_anchor=lambda request: sends.append(request) or TX,
            read_anchor=found,
        )
    assert ok is True
    assert uploads == []
    assert sends == []
    db = session_factory()
    try:
        row = db.query(VideoRecord).one()
        assert row.ipfs_cid == CID
        assert row.tx_hash == TX
        assert _as_utc(row.ended_at) == stored_end
    finally:
        db.close()
