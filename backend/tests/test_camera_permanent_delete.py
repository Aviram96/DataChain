"""Permanent deletion of an empty archived camera. Isolated SQLite.

Pinata, FFmpeg, and the chain are mocked. Local files are not removed.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.deps import get_db
from app.main import app
from app.models.camera import Camera
from app.models.verification_attempt import (
    VerificationAttempt,
    VerificationAttemptMinute,
)
from app.models.video_record import VideoRecord
from app.services.camera_deletion import (
    HAS_DEPENDENT_DATA,
    permanently_delete_camera,
)
from app.services.cctv_feed_simulator import DEFAULT_FFMPEG
from app.services.ingest_segment_processor import (
    CameraNotRecordable,
    persist_video_record,
)

import app.models as _models  # noqa: F401

TEST_PASSWORD = "test-password-12"
CID = "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi"
FILE_HASH = "ab" * 32
TX = "0x" + "cd" * 32
NOON = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def db_session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def stub_camera_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.routers.cameras.probe_status", lambda _url: "offline")
    monkeypatch.setattr(
        "app.routers.cameras.probe_many_statuses",
        lambda urls: ["offline"] * len(urls),
    )


@pytest.fixture
def client(db_session: Session) -> TestClient:
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def isolated_checks(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict:
    """Writer checks use a throwaway directory. External services are not called."""
    temp = tmp_path / "temp"
    quarantine = tmp_path / "quarantine"
    temp.mkdir()
    quarantine.mkdir()
    state = {"temp": temp, "quarantine": quarantine, "network": []}

    def no_network(*_args: object, **_kwargs: object) -> None:
        state["network"].append("pinata")
        raise AssertionError("real Pinata request")

    def no_chain(*_args: object, **_kwargs: object) -> None:
        state["network"].append("chain")
        raise AssertionError("blockchain call")

    monkeypatch.setattr(
        "app.services.camera_deletion.temp_root_for_cleanup", lambda: temp
    )
    monkeypatch.setattr(
        "app.services.camera_deletion.quarantine_root_for_cleanup",
        lambda: quarantine,
    )
    monkeypatch.setattr(
        "app.services.camera_deletion.list_process_commands",
        lambda: [],
    )
    monkeypatch.setattr("app.services.pinata_ipfs.requests.delete", no_network)
    monkeypatch.setattr("app.services.pinata_ipfs.requests.post", no_network)
    monkeypatch.setattr("app.services.chain_anchor.anchor_segment", no_chain)
    monkeypatch.setattr("app.services.chain_anchor.get_segment", no_chain)
    return state


def _register(client: TestClient, email: str) -> str:
    response = client.post(
        "/auth/register",
        json={"email": email, "password": TEST_PASSWORD},
    )
    assert response.status_code == 201
    login = client.post(
        "/auth/login",
        json={"email": email, "password": TEST_PASSWORD},
    )
    assert login.status_code == 200
    return login.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create(client: TestClient, token: str, name: str) -> str:
    response = client.post(
        "/cameras",
        headers=_auth(token),
        json={"name": name, "stream_url": "rtsp://192.0.2.20/live"},
    )
    assert response.status_code == 201
    return response.json()["id"]


def _archive(client: TestClient, token: str, camera_id: str) -> None:
    response = client.post(f"/cameras/{camera_id}/archive", headers=_auth(token))
    assert response.status_code == 200
    assert response.json()["lifecycle"] == "archived"


def _add_recording(db: Session, camera_id: str) -> VideoRecord:
    record = VideoRecord(
        id=uuid4(),
        camera_id=UUID(camera_id),
        started_at=NOON,
        ended_at=NOON + timedelta(seconds=60),
        ipfs_cid=CID,
        segment_hash=FILE_HASH,
        tx_hash=TX,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def _add_attempt(db: Session, camera_id: str) -> VerificationAttempt:
    camera = db.get(Camera, UUID(camera_id))
    assert camera is not None
    attempt = VerificationAttempt(
        id=uuid4(),
        user_id=camera.user_id,
        camera_id=camera.id,
        started_at=NOON,
        ended_at=NOON + timedelta(minutes=1),
        scope="minute",
        overall_status="verified",
    )
    db.add(attempt)
    db.flush()
    db.add(
        VerificationAttemptMinute(
            id=uuid4(),
            attempt_id=attempt.id,
            started_at=NOON,
            status="verified",
            detail="ok",
            video_record_id=None,
        )
    )
    db.commit()
    return attempt


def _delete(client: TestClient, token: str, camera_id: str, name: str):
    return client.post(
        f"/cameras/{camera_id}/permanent-delete",
        headers=_auth(token),
        json={"confirm_name": name},
    )


def _count(db: Session, model: type) -> int:
    value = db.scalar(select(func.count()).select_from(model))
    return int(value or 0)


def test_owner_deletes_an_empty_archived_camera(
    client: TestClient,
    db_session: Session,
    isolated_checks: dict,
) -> None:
    token = _register(client, "empty@example.com")
    camera_id = _create(client, token, "Lobby")
    _archive(client, token, camera_id)
    folder = isolated_checks["temp"] / camera_id
    folder.mkdir()
    segment = folder / "segment.mp4"
    segment.write_bytes(b"leave-me")

    response = _delete(client, token, camera_id, "Lobby")

    assert response.status_code == 200
    assert response.json()["deleted"] is True
    assert response.json()["message"] == "Camera deleted."
    db_session.expire_all()
    assert db_session.get(Camera, UUID(camera_id)) is None
    assert segment.read_bytes() == b"leave-me"
    assert isolated_checks["network"] == []
    missing = _delete(client, token, camera_id, "Lobby")
    assert missing.status_code == 404


def test_recordings_and_verification_history_block_deletion(
    client: TestClient,
    db_session: Session,
    isolated_checks: dict,
) -> None:
    token = _register(client, "kept@example.com")
    with_recording = _create(client, token, "With clip")
    record = _add_recording(db_session, with_recording)
    _archive(client, token, with_recording)
    rejected = _delete(client, token, with_recording, "With clip")
    assert rejected.status_code == 409
    assert rejected.json()["detail"] == HAS_DEPENDENT_DATA

    with_attempt = _create(client, token, "With audit")
    attempt = _add_attempt(db_session, with_attempt)
    _archive(client, token, with_attempt)
    audit = _delete(client, token, with_attempt, "With audit")
    assert audit.status_code == 409
    assert audit.json()["detail"] == HAS_DEPENDENT_DATA

    db_session.expire_all()
    assert db_session.get(Camera, UUID(with_recording)) is not None
    assert db_session.get(VideoRecord, record.id) is not None
    assert db_session.get(VideoRecord, record.id).tx_hash == TX
    assert db_session.get(VerificationAttempt, attempt.id) is not None
    assert _count(db_session, VerificationAttemptMinute) == 1
    assert isolated_checks["network"] == []


def test_other_user_active_camera_and_wrong_name_delete_nothing(
    client: TestClient,
    db_session: Session,
    isolated_checks: dict,
) -> None:
    owner = _register(client, "owner@example.com")
    intruder = _register(client, "intruder@example.com")
    camera_id = _create(client, owner, "Lobby")

    active = _delete(client, owner, camera_id, "nope")
    assert active.status_code == 409
    assert active.json()["detail"] == (
        "Only archived cameras can be permanently deleted."
    )

    _archive(client, owner, camera_id)
    wrong = _delete(client, owner, camera_id, "Lobby ")
    assert wrong.status_code == 400
    assert wrong.json()["detail"] == "Camera name confirmation does not match."
    hidden = _delete(client, intruder, camera_id, "Lobby")
    assert hidden.status_code == 404
    unauthenticated = client.post(
        f"/cameras/{camera_id}/permanent-delete",
        json={"confirm_name": "Lobby"},
    )
    assert unauthenticated.status_code == 401
    db_session.expire_all()
    assert db_session.get(Camera, UUID(camera_id)) is not None
    assert isolated_checks["network"] == []


def test_archive_and_restore_do_not_call_pinata_or_chain(
    client: TestClient,
    isolated_checks: dict,
) -> None:
    token = _register(client, "archive@example.com")
    camera_id = _create(client, token, "Gate")
    archived = client.delete(f"/cameras/{camera_id}", headers=_auth(token))
    assert archived.status_code == 204
    restored = client.post(f"/cameras/{camera_id}/restore", headers=_auth(token))
    assert restored.status_code == 200
    assert restored.json()["lifecycle"] == "active"
    assert isolated_checks["network"] == []


def test_ingest_lock_and_live_ffmpeg_reject_before_delete(
    client: TestClient,
    db_session: Session,
    isolated_checks: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = _register(client, "busy@example.com")
    camera_id = _create(client, token, "Busy")
    _archive(client, token, camera_id)
    monkeypatch.setattr(
        "app.services.camera_deletion.try_hold_ingest_locks",
        lambda _db, _camera_id: False,
    )
    locked = _delete(client, token, camera_id, "Busy")
    assert locked.status_code == 409
    assert "still recording" in locked.json()["detail"]

    monkeypatch.setattr(
        "app.services.camera_deletion.try_hold_ingest_locks",
        lambda _db, _camera_id: True,
    )
    monkeypatch.setattr(
        "app.services.camera_deletion.list_process_commands",
        lambda: [f"{DEFAULT_FFMPEG} -i rtsp://example {camera_id}/out.mp4"],
    )
    live = _delete(client, token, camera_id, "Busy")
    assert live.status_code == 409
    assert "still recording" in live.json()["detail"]
    db_session.expire_all()
    assert db_session.get(Camera, UUID(camera_id)) is not None
    assert isolated_checks["network"] == []


def test_failed_commit_does_not_delete_the_camera(
    client: TestClient,
    db_session: Session,
    isolated_checks: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = _register(client, "commit@example.com")
    camera_id = _create(client, token, "Commit")
    _archive(client, token, camera_id)
    camera = db_session.get(Camera, UUID(camera_id))
    assert camera is not None

    def fail_commit() -> None:
        raise RuntimeError("commit failed")

    monkeypatch.setattr(db_session, "commit", fail_commit)
    with pytest.raises(RuntimeError, match="commit failed"):
        permanently_delete_camera(
            db_session,
            camera_id=camera.id,
            owner_id=camera.user_id,
            confirm_name="Commit",
            temp_root=isolated_checks["temp"],
            quarantine_root=isolated_checks["quarantine"],
            command_lister=lambda: [],
        )
    db_session.rollback()
    db_session.expire_all()
    assert db_session.get(Camera, UUID(camera_id)) is not None


def test_archived_camera_cannot_receive_a_new_recording(
    client: TestClient,
    db_session: Session,
) -> None:
    token = _register(client, "archived-ingest@example.com")
    camera_id = _create(client, token, "Paused")
    _archive(client, token, camera_id)
    with pytest.raises(CameraNotRecordable):
        persist_video_record(
            db_session,
            camera_id=UUID(camera_id),
            started_at=NOON,
            ended_at=NOON + timedelta(seconds=60),
            ipfs_cid=CID,
            segment_hash=FILE_HASH,
            tx_hash=TX,
        )
    assert _count(db_session, VideoRecord) == 0
