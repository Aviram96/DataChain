"""Playback and download write one server-side verification audit."""

from __future__ import annotations

import hashlib
import logging
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
from app.models.verification_attempt import (
    VerificationAttempt,
    VerificationAttemptMinute,
)
from app.models.video_record import VideoRecord
from app.services.chain_anchor import (
    ChainAnchorError,
    ChainAnchorNotFoundError,
    SegmentAnchor,
)
from app.services.recording_download import RecordingDownloadError

import app.models as _models  # noqa: F401

TEST_PASSWORD = "test-password-12"
CID = "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi"
VIDEO = b"verified-audit-bytes"
TX = "0x" + "ab" * 32
NOON = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def db_session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def stub_camera_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.routers.cameras.probe_status",
        lambda _url: "offline",
    )
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


def _register_and_token(client: TestClient, email: str) -> tuple[str, str]:
    response = client.post(
        "/auth/register",
        json={"email": email, "password": TEST_PASSWORD},
    )
    assert response.status_code == 201
    user_id = response.json()["id"]
    login = client.post(
        "/auth/login",
        json={"email": email, "password": TEST_PASSWORD},
    )
    assert login.status_code == 200
    return user_id, login.json()["access_token"]


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_camera(client: TestClient, token: str, name: str = "Gate") -> str:
    created = client.post(
        "/cameras",
        headers=_auth_headers(token),
        json={"name": name, "stream_url": "rtsp://192.0.2.50/live"},
    )
    assert created.status_code == 201
    return created.json()["id"]


def _add_segment(
    db: Session,
    camera_id: str,
    started: datetime,
    *,
    body: bytes = VIDEO,
) -> VideoRecord:
    record = VideoRecord(
        id=uuid4(),
        camera_id=UUID(camera_id),
        started_at=started,
        ended_at=started + timedelta(seconds=60),
        ipfs_cid=CID if body == VIDEO else f"bafy{uuid4().hex}",
        segment_hash=hashlib.sha256(body).hexdigest(),
        tx_hash=TX,
        created_at=datetime.now(timezone.utc),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def _install_playback(
    monkeypatch: pytest.MonkeyPatch,
    record: VideoRecord,
    *,
    mode: str,
) -> None:
    def get_segment(
        camera_id: UUID, started_at: datetime, **_kwargs: object
    ) -> SegmentAnchor:
        if mode == "missing":
            raise ChainAnchorNotFoundError()
        if mode == "failed":
            raise ChainAnchorError("On-chain segment read failed: timeout")
        ended = record.ended_at
        if ended.tzinfo is None:
            ended = ended.replace(tzinfo=timezone.utc)
        cid = "bafy-tampered" if mode == "tampered" else record.ipfs_cid
        return SegmentAnchor(
            camera_id=camera_id,
            started_at=started_at,
            ended_at=ended,
            cid=cid,
            segment_hash=record.segment_hash,
        )

    def fetch(cid: str, dest: Path, **_kwargs: object) -> None:
        if mode == "unavailable":
            raise RecordingDownloadError("Could not retrieve a segment from IPFS.")
        dest.write_bytes(VIDEO)

    monkeypatch.setattr(
        "app.services.recording_verification.get_segment",
        get_segment,
    )
    monkeypatch.setattr(
        "app.services.recording_verification.fetch_cid_to_file",
        fetch,
    )


def _unix(moment: datetime) -> int:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return int(moment.timestamp())


def _install_download(
    monkeypatch: pytest.MonkeyPatch,
    records: list[VideoRecord],
    modes: dict[UUID, str],
) -> None:
    by_start = {_unix(record.started_at): record for record in records}

    def get_segment(
        camera_id: UUID, started_at: datetime, **_kwargs: object
    ) -> SegmentAnchor:
        record = by_start[_unix(started_at)]
        mode = modes[record.id]
        if mode == "tampered":
            cid = "bafy-tampered"
        else:
            cid = record.ipfs_cid
        ended = record.ended_at
        if ended.tzinfo is None:
            ended = ended.replace(tzinfo=timezone.utc)
        return SegmentAnchor(
            camera_id=camera_id,
            started_at=started_at,
            ended_at=ended,
            cid=cid,
            segment_hash=record.segment_hash,
        )

    def fetch(cid: str, dest: Path, **_kwargs: object) -> None:
        if cid == "bafy-tampered":
            dest.write_bytes(b"tampered-bytes")
            return
        record = next(item for item in records if item.ipfs_cid == cid)
        if modes[record.id] == "unavailable":
            raise RecordingDownloadError("Could not retrieve a segment from IPFS.")
        dest.write_bytes(VIDEO)

    monkeypatch.setattr(
        "app.services.recording_verification.get_segment",
        get_segment,
    )
    monkeypatch.setattr(
        "app.services.recording_verification.fetch_cid_to_file",
        fetch,
    )


def _attempts(db: Session) -> list[VerificationAttempt]:
    db.expire_all()
    return list(db.scalars(select(VerificationAttempt)).all())


def _play(
    client: TestClient,
    token: str,
    camera_id: str,
    record_id: UUID,
):
    return client.get(
        f"/cameras/{camera_id}/recordings/{record_id}/playback",
        headers=_auth_headers(token),
    )


def _download(
    client: TestClient,
    token: str,
    camera_id: str,
    started: datetime,
    ended: datetime,
):
    return client.get(
        f"/cameras/{camera_id}/recordings/download",
        headers=_auth_headers(token),
        params={
            "started_at": started.isoformat(),
            "ended_at": ended.isoformat(),
        },
    )


def test_verified_playback_writes_one_audit(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    user_id, token = _register_and_token(client, "audit-play@example.com")
    camera_id = _create_camera(client, token)
    record = _add_segment(db_session, camera_id, NOON)
    work = tmp_path / "playback"
    work.mkdir()
    monkeypatch.setattr("app.routers.recordings._playback_work_dir", lambda: work)
    _install_playback(monkeypatch, record, mode="verified")

    response = _play(client, token, camera_id, record.id)

    assert response.status_code == 200
    assert response.content == VIDEO
    attempts = _attempts(db_session)
    assert len(attempts) == 1
    attempt = attempts[0]
    assert str(attempt.user_id) == user_id
    assert str(attempt.camera_id) == camera_id
    assert attempt.operation == "playback"
    assert attempt.overall_status == "verified"
    assert attempt.created_at is not None
    assert len(attempt.minutes) == 1
    minute = attempt.minutes[0]
    assert minute.status == "verified"
    assert minute.video_record_id == record.id
    assert minute.detail


def test_failed_playback_records_segment_status(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _user_id, token = _register_and_token(client, "audit-fail@example.com")
    camera_id = _create_camera(client, token)
    record = _add_segment(db_session, camera_id, NOON)
    work = tmp_path / "playback"
    work.mkdir()
    monkeypatch.setattr("app.routers.recordings._playback_work_dir", lambda: work)
    _install_playback(monkeypatch, record, mode="failed")

    response = _play(client, token, camera_id, record.id)

    assert response.status_code == 409
    assert response.json()["overall"] == "failed"
    attempts = _attempts(db_session)
    assert len(attempts) == 1
    assert attempts[0].operation == "playback"
    assert attempts[0].overall_status == "failed"
    assert attempts[0].minutes[0].status == "failed"
    assert attempts[0].minutes[0].video_record_id == record.id
    assert "blockchain read failed" in attempts[0].minutes[0].detail


def test_playback_denied_to_other_owner_writes_nothing(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _owner_id, owner = _register_and_token(client, "audit-owner@example.com")
    _other_id, other = _register_and_token(client, "audit-other@example.com")
    camera_id = _create_camera(client, owner)
    record = _add_segment(db_session, camera_id, NOON)

    def forbid(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("verification must not run for another owner")

    monkeypatch.setattr(
        "app.services.recording_verification.get_segment",
        forbid,
    )
    response = _play(client, other, camera_id, record.id)

    assert response.status_code == 404
    assert _attempts(db_session) == []


def test_archived_camera_playback_is_audited(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    user_id, token = _register_and_token(client, "audit-archived@example.com")
    camera_id = _create_camera(client, token)
    record = _add_segment(db_session, camera_id, NOON)
    archived = client.post(
        f"/cameras/{camera_id}/archive",
        headers=_auth_headers(token),
    )
    assert archived.status_code == 200
    work = tmp_path / "playback"
    work.mkdir()
    monkeypatch.setattr("app.routers.recordings._playback_work_dir", lambda: work)
    _install_playback(monkeypatch, record, mode="verified")

    response = _play(client, token, camera_id, record.id)

    assert response.status_code == 200
    attempts = _attempts(db_session)
    assert len(attempts) == 1
    assert str(attempts[0].user_id) == user_id
    assert str(attempts[0].camera_id) == camera_id
    assert attempts[0].operation == "playback"
    listed = client.get(
        f"/cameras/{camera_id}/verification-attempts",
        headers=_auth_headers(token),
    )
    assert listed.status_code == 404


def test_verified_download_writes_one_audit(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    user_id, token = _register_and_token(client, "audit-dl@example.com")
    camera_id = _create_camera(client, token)
    record = _add_segment(db_session, camera_id, NOON)
    work = tmp_path / "download"
    work.mkdir()
    monkeypatch.setattr("app.routers.recordings._download_work_dir", lambda: work)
    _install_download(monkeypatch, [record], {record.id: "verified"})

    response = _download(
        client,
        token,
        camera_id,
        NOON,
        NOON + timedelta(seconds=60),
    )

    assert response.status_code == 200
    assert VIDEO in response.content
    attempts = _attempts(db_session)
    assert len(attempts) == 1
    attempt = attempts[0]
    assert str(attempt.user_id) == user_id
    assert str(attempt.camera_id) == camera_id
    assert attempt.operation == "download"
    assert attempt.overall_status == "verified"
    assert len(attempt.minutes) == 1
    assert attempt.minutes[0].status == "verified"
    assert attempt.minutes[0].video_record_id == record.id


def test_partial_download_records_each_segment(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _user_id, token = _register_and_token(client, "audit-partial@example.com")
    camera_id = _create_camera(client, token)
    good = _add_segment(db_session, camera_id, NOON, body=VIDEO)
    bad = _add_segment(
        db_session,
        camera_id,
        NOON + timedelta(seconds=60),
        body=b"other-segment",
    )
    work = tmp_path / "download"
    work.mkdir()
    monkeypatch.setattr("app.routers.recordings._download_work_dir", lambda: work)
    _install_download(
        monkeypatch,
        [good, bad],
        {good.id: "verified", bad.id: "unavailable"},
    )

    response = _download(client, token, camera_id, NOON, bad.ended_at)

    assert response.status_code == 200
    assert VIDEO in response.content
    attempts = _attempts(db_session)
    assert len(attempts) == 1
    assert attempts[0].operation == "download"
    assert attempts[0].overall_status == "unavailable"
    statuses = {minute.video_record_id: minute.status for minute in attempts[0].minutes}
    assert statuses == {good.id: "verified", bad.id: "unavailable"}
    unavailable = next(
        minute for minute in attempts[0].minutes if minute.video_record_id == bad.id
    )
    assert "could not be retrieved" in unavailable.detail


@pytest.mark.parametrize("mode", ["tampered", "missing", "unavailable"])
def test_unsuccessful_playback_statuses_are_stored(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mode: str,
) -> None:
    _user_id, token = _register_and_token(client, f"audit-{mode}@example.com")
    camera_id = _create_camera(client, token)
    record = _add_segment(db_session, camera_id, NOON)
    work = tmp_path / "playback"
    work.mkdir()
    monkeypatch.setattr("app.routers.recordings._playback_work_dir", lambda: work)
    _install_playback(monkeypatch, record, mode=mode)

    response = _play(client, token, camera_id, record.id)

    assert response.status_code == 409
    assert response.json()["segments"][0]["status"] == mode
    attempts = _attempts(db_session)
    assert len(attempts) == 1
    assert attempts[0].overall_status == mode
    assert attempts[0].minutes[0].status == mode
    assert attempts[0].minutes[0].detail == response.json()["segments"][0]["detail"]


def test_audit_failure_keeps_playback_and_saves_nothing(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _user_id, token = _register_and_token(client, "audit-db@example.com")
    camera_id = _create_camera(client, token)
    record = _add_segment(db_session, camera_id, NOON)
    work = tmp_path / "playback"
    work.mkdir()
    monkeypatch.setattr("app.routers.recordings._playback_work_dir", lambda: work)
    _install_playback(monkeypatch, record, mode="verified")

    def fail_commit() -> None:
        raise RuntimeError("audit store unavailable")

    monkeypatch.setattr(db_session, "commit", fail_commit)
    caplog.set_level(logging.ERROR)

    response = _play(client, token, camera_id, record.id)

    assert response.status_code == 200
    assert response.content == VIDEO
    assert "Verification audit was not saved" in caplog.text
    assert "audit store unavailable" in caplog.text
    count = db_session.scalar(select(func.count()).select_from(VerificationAttempt))
    minute_count = db_session.scalar(
        select(func.count()).select_from(VerificationAttemptMinute)
    )
    assert count == 0
    assert minute_count == 0
