"""Mocked integration: IPFS CID → chain tx → PostgreSQL row (CP-D.P9).

Pinata HTTP and the Web3 send path are mocked. The real ``upload_segment``
and ``anchor_segment`` helpers still run so the CID and tx hash must match
across chain request and ``video_records``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
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
from app.services.chain_anchor import SegmentAnchorRequest, anchor_segment
from app.services.ingest_segment_processor import process_ingest_segment
from app.services.segment_integrity import sha256_file
from app.services.segment_staging import staging_dir_for_camera

import app.models as _models  # noqa: F401

CAMERA_ID = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
STARTED = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
ENDED = STARTED + timedelta(seconds=60)
CID = "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi"
TX = "0x" + "cd" * 32


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
    user = User(email="p9@example.com", password_hash=hash_password("password12"))
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


def _as_utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def test_ipfs_anchor_db_cid_and_tx_hash_match(
    tmp_path: Path, session_factory: sessionmaker, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _segment(tmp_path)
    digest = sha256_file(path)
    monkeypatch.setenv("PINATA_JWT", "test-jwt")
    seen: list[SegmentAnchorRequest] = []

    def send_once(request: SegmentAnchorRequest) -> str:
        seen.append(request)
        return TX

    pinata = MagicMock()
    pinata.status_code = 200
    pinata.json.return_value = {"IpfsHash": CID}

    with patch("app.services.pinata_ipfs.requests.post", return_value=pinata) as post:
        ok = process_ingest_segment(
            path,
            duration_seconds=60,
            session_factory=session_factory,
            send_anchor=lambda req: anchor_segment(
                req, send_once=send_once, max_attempts=1
            ),
        )

    assert ok is True
    post.assert_called_once()
    assert len(seen) == 1
    request = seen[0]
    assert request.cid == CID
    assert request.segment_hash == digest
    assert request.camera_id == CAMERA_ID
    assert request.started_at == STARTED
    assert request.ended_at == ENDED

    db: Session = session_factory()
    try:
        row = db.query(VideoRecord).one()
        assert row.camera_id == CAMERA_ID
        assert _as_utc(row.started_at) == STARTED
        assert _as_utc(row.ended_at) == ENDED
        assert row.ipfs_cid == CID
        assert row.ipfs_cid == request.cid
        assert row.tx_hash == TX
        assert row.segment_hash == digest
        assert row.segment_hash == request.segment_hash
    finally:
        db.close()
