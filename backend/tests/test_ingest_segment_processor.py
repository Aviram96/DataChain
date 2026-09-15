"""Tests for ingest Pinata + chain + DB processing (Slice D)."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

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
from app.services.chain_anchor import ChainAnchorError, SegmentAnchorRequest
from app.services.chunk_processing_worker import ChunkProcessingWorker
from app.services.ingest_segment_processor import process_ingest_segment
from app.services.pinata_ipfs import PinataUploadError
from app.services.segment_identity import camera_segment_pattern
from app.services.segment_integrity import SegmentIntegrityResult
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


def test_process_success_saves_row_and_can_delete(
    tmp_path: Path, session_factory: sessionmaker
) -> None:
    path = _segment(tmp_path)
    ok = process_ingest_segment(
        path,
        duration_seconds=60,
        session_factory=session_factory,
        upload=lambda _p: CID,
        send_anchor=lambda _req: TX,
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

    def fail_upload(_p: Path) -> str:
        raise PinataUploadError("no pinata")

    assert (
        process_ingest_segment(
            path,
            session_factory=session_factory,
            upload=fail_upload,
            send_anchor=lambda _req: TX,
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

    def fail_anchor(_req: SegmentAnchorRequest) -> str:
        raise ChainAnchorError("RPC timeout")

    assert (
        process_ingest_segment(
            path,
            session_factory=session_factory,
            upload=lambda _p: CID,
            send_anchor=fail_anchor,
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
    )
    worker = ChunkProcessingWorker(worker_config)
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
