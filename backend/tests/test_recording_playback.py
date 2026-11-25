"""Watch serves a segment only after backend verification."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import anyio
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.deps import get_db
from app.main import app
from app.models.video_record import VideoRecord
from app.routers.recordings import _CleanupFileResponse
from app.services.chain_anchor import (
    ChainAnchorError,
    ChainAnchorNotFoundError,
    SegmentAnchor,
)
from app.services.recording_download import RecordingDownloadError

import app.models as _models  # noqa: F401

TEST_PASSWORD = "test-password-12"
CID = "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi"
VIDEO = b"verified-playback-bytes"
FILE_HASH = hashlib.sha256(VIDEO).hexdigest()
TX = "0x" + "bb" * 32
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


def _register_and_token(client: TestClient, email: str) -> str:
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
    segment_hash: str = FILE_HASH,
) -> VideoRecord:
    record = VideoRecord(
        id=uuid4(),
        camera_id=UUID(camera_id),
        started_at=started,
        ended_at=started + timedelta(seconds=60),
        ipfs_cid=CID,
        segment_hash=segment_hash,
        tx_hash=TX,
        created_at=datetime.now(timezone.utc),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def _pin_work_dir(monkeypatch: pytest.MonkeyPatch, work: Path) -> None:
    work.mkdir()
    monkeypatch.setattr("app.routers.recordings._playback_work_dir", lambda: work)


def _install_sources(
    monkeypatch: pytest.MonkeyPatch,
    record: VideoRecord,
    *,
    mode: str,
    fetched: list[str],
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
        fetched.append(cid)
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


def _playback_url(camera_id: str, record_id: UUID) -> str:
    return f"/cameras/{camera_id}/recordings/{record_id}/playback"


def test_playback_requires_auth(client: TestClient) -> None:
    response = client.get(_playback_url(str(uuid4()), uuid4()))
    assert response.status_code == 401


def test_playback_hidden_from_other_owner(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token_a = _register_and_token(client, "owner-a@example.com")
    token_b = _register_and_token(client, "owner-b@example.com")
    camera_id = _create_camera(client, token_a)
    record = _add_segment(db_session, camera_id, NOON)

    def forbid(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("verification must not run for another owner")

    monkeypatch.setattr(
        "app.services.recording_verification.get_segment",
        forbid,
    )
    response = client.get(
        _playback_url(camera_id, record.id),
        headers=_auth_headers(token_b),
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Camera not found."


def test_playback_unknown_recording_is_not_found(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = _register_and_token(client, "missing-row@example.com")
    camera_id = _create_camera(client, token)

    def forbid(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("verification must not run without a recording")

    monkeypatch.setattr(
        "app.services.recording_verification.get_segment",
        forbid,
    )
    response = client.get(
        _playback_url(camera_id, uuid4()),
        headers=_auth_headers(token),
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Recording not found."


def test_verified_playback_returns_media_and_deletes_temp_files(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = _register_and_token(client, "watch@example.com")
    camera_id = _create_camera(client, token)
    record = _add_segment(db_session, camera_id, NOON)
    work = tmp_path / "playback-work"
    _pin_work_dir(monkeypatch, work)
    fetched: list[str] = []
    _install_sources(monkeypatch, record, mode="verified", fetched=fetched)

    response = client.get(
        _playback_url(camera_id, record.id),
        headers=_auth_headers(token),
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("video/mp4")
    assert response.content == VIDEO
    assert fetched == [CID]
    assert str(work) not in response.text
    assert "work_dir" not in response.headers.get("content-disposition", "")
    assert not work.exists()


@pytest.mark.parametrize(
    ("mode", "status_name"),
    [
        ("tampered", "tampered"),
        ("missing", "missing"),
        ("unavailable", "unavailable"),
        ("failed", "failed"),
    ],
)
def test_failed_verification_returns_json_and_no_media(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    status_name: str,
) -> None:
    token = _register_and_token(client, f"{mode}@example.com")
    camera_id = _create_camera(client, token)
    record = _add_segment(db_session, camera_id, NOON)
    work = tmp_path / "playback-work"
    _pin_work_dir(monkeypatch, work)
    fetched: list[str] = []
    _install_sources(monkeypatch, record, mode=mode, fetched=fetched)

    response = client.get(
        _playback_url(camera_id, record.id),
        headers=_auth_headers(token),
    )

    assert response.status_code == 409
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert body["overall"] == status_name
    assert body["segments"][0]["status"] == status_name
    assert body["segments"][0]["video_record_id"] == str(record.id)
    assert body["detail"]
    assert VIDEO not in response.content
    assert str(work) not in response.text
    assert "work_dir" not in response.text
    assert not work.exists()
    if mode in {"tampered", "missing", "failed"}:
        assert fetched == []


def test_playback_response_deletes_temp_dir_when_send_fails(tmp_path: Path) -> None:
    work = tmp_path / "cancelled"
    work.mkdir()
    video = work / "clip.mp4"
    video.write_bytes(VIDEO)
    response = _CleanupFileResponse(
        path=video,
        cleanup_dir=str(work),
        media_type="video/mp4",
        filename="recording.mp4",
        content_disposition_type="inline",
    )

    async def receive() -> dict[str, str]:
        return {"type": "http.request"}

    async def send(message: dict[str, object]) -> None:
        if message["type"] == "http.response.body":
            raise RuntimeError("client cancelled")

    with pytest.raises(RuntimeError, match="client cancelled"):
        anyio.run(
            response,
            {"type": "http", "method": "GET", "headers": []},
            receive,
            send,
        )

    assert not work.exists()
