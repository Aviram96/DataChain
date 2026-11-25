"""Archive and restore: ownership, history, and name conflicts.

Uses an isolated in-memory SQLite database. Chain and IPFS calls are mocked.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.deps import get_db
from app.main import app
from app.models.camera import Camera
from app.models.video_record import VideoRecord
from app.services.chain_anchor import SegmentAnchor

import app.models as _models  # noqa: F401

TEST_PASSWORD = "test-password-12"
CID = "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi"
VIDEO = b"archived-verified-bytes"
FILE_HASH = hashlib.sha256(VIDEO).hexdigest()
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


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create(client: TestClient, token: str, name: str, url: str) -> dict[str, object]:
    response = client.post(
        "/cameras",
        headers=_auth(token),
        json={"name": name, "stream_url": url},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["lifecycle"] == "active"
    assert body["archived_at"] is None
    return body


def _add_recording(db: Session, camera_id: str) -> VideoRecord:
    record = VideoRecord(
        id=uuid4(),
        camera_id=UUID(camera_id),
        started_at=NOON,
        ended_at=NOON + timedelta(seconds=60),
        ipfs_cid=CID,
        segment_hash=FILE_HASH,
        tx_hash=TX,
        created_at=datetime.now(timezone.utc),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def test_archive_hides_camera_and_keeps_recordings(
    client: TestClient, db_session: Session
) -> None:
    token = _register_and_token(client, "owner@example.com")
    created = _create(client, token, "Lobby", "rtsp://192.0.2.10/live")
    camera_id = str(created["id"])
    record = _add_recording(db_session, camera_id)

    archived = client.post(f"/cameras/{camera_id}/archive", headers=_auth(token))
    assert archived.status_code == 200
    body = archived.json()
    assert body["id"] == camera_id
    assert body["lifecycle"] == "archived"
    assert body["archived_at"] is not None
    assert body["offline_reason"] is None
    assert body["ingest_offline_at"] is None

    active = client.get("/cameras", headers=_auth(token))
    assert active.status_code == 200
    assert active.json()["total"] == 0

    listed = client.get("/cameras/archived", headers=_auth(token))
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["id"] == camera_id
    assert listed.json()["items"][0]["lifecycle"] == "archived"

    detail = client.get(f"/cameras/{camera_id}", headers=_auth(token))
    assert detail.status_code == 200
    assert detail.json()["lifecycle"] == "archived"

    recordings = client.get(f"/cameras/{camera_id}/recordings", headers=_auth(token))
    assert recordings.status_code == 200
    assert recordings.json()["total"] == 1
    item = recordings.json()["items"][0]
    assert item["id"] == str(record.id)
    assert item["camera_id"] == camera_id
    assert item["ipfs_cid"] == CID
    assert item["tx_hash"] == TX

    db_session.expire_all()
    row = db_session.get(Camera, UUID(camera_id))
    stored = db_session.get(VideoRecord, record.id)
    assert row is not None and row.deleted_at is not None
    assert stored is not None
    assert stored.camera_id == UUID(camera_id)
    assert stored.ipfs_cid == CID
    assert stored.tx_hash == TX


def test_archive_again_and_edit_do_not_change_the_row(
    client: TestClient, db_session: Session
) -> None:
    token = _register_and_token(client, "twice@example.com")
    camera_id = str(_create(client, token, "Yard", "rtsp://192.0.2.11/live")["id"])
    first = client.post(f"/cameras/{camera_id}/archive", headers=_auth(token))
    assert first.status_code == 200
    archived_at = first.json()["archived_at"]

    again = client.post(f"/cameras/{camera_id}/archive", headers=_auth(token))
    assert again.status_code == 409
    edited = client.patch(
        f"/cameras/{camera_id}",
        headers=_auth(token),
        json={"name": "Renamed"},
    )
    assert edited.status_code == 409

    db_session.expire_all()
    row = db_session.get(Camera, UUID(camera_id))
    assert row is not None
    assert row.name == "Yard"
    assert row.deleted_at is not None
    detail = client.get(f"/cameras/{camera_id}", headers=_auth(token))
    assert detail.json()["archived_at"] == archived_at
    assert detail.json()["name"] == "Yard"


def test_restore_keeps_the_same_id_and_does_not_start_ingest(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started: list[str] = []

    class Started:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            started.append("constructed")

        def run_until_signal(self) -> int:
            started.append("ran")
            return 0

    monkeypatch.setattr("app.services.camera_ingest.CameraIngest", Started)

    def forbid_process(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("restore started a process")

    monkeypatch.setattr("subprocess.Popen", forbid_process)

    token = _register_and_token(client, "restore@example.com")
    camera_id = str(_create(client, token, "Gate", "rtsp://192.0.2.12/live")["id"])
    record = _add_recording(db_session, camera_id)
    assert (
        client.post(f"/cameras/{camera_id}/archive", headers=_auth(token)).status_code
        == 200
    )

    restored = client.post(f"/cameras/{camera_id}/restore", headers=_auth(token))
    assert restored.status_code == 200
    body = restored.json()
    assert body["id"] == camera_id
    assert body["lifecycle"] == "active"
    assert body["archived_at"] is None
    assert started == []

    active = client.get("/cameras", headers=_auth(token))
    assert [item["id"] for item in active.json()["items"]] == [camera_id]
    archived = client.get("/cameras/archived", headers=_auth(token))
    assert archived.json()["total"] == 0

    db_session.expire_all()
    stored = db_session.get(VideoRecord, record.id)
    assert stored is not None
    assert stored.camera_id == UUID(camera_id)
    assert stored.ipfs_cid == CID
    assert stored.tx_hash == TX


def test_restore_conflict_leaves_both_cameras_unchanged(
    client: TestClient, db_session: Session
) -> None:
    token = _register_and_token(client, "conflict@example.com")
    original_id = str(_create(client, token, "Lobby", "rtsp://192.0.2.13/live")["id"])
    record = _add_recording(db_session, original_id)
    assert (
        client.post(f"/cameras/{original_id}/archive", headers=_auth(token)).status_code
        == 200
    )
    replacement_id = str(
        _create(client, token, "lobby", "rtsp://192.0.2.14/live")["id"]
    )

    refused = client.post(f"/cameras/{original_id}/restore", headers=_auth(token))
    assert refused.status_code == 409
    assert "already have a camera" in refused.json()["detail"].lower()

    db_session.expire_all()
    original = db_session.get(Camera, UUID(original_id))
    replacement = db_session.get(Camera, UUID(replacement_id))
    stored = db_session.get(VideoRecord, record.id)
    assert original is not None and original.deleted_at is not None
    assert original.name == "Lobby"
    assert replacement is not None and replacement.deleted_at is None
    assert replacement.name == "lobby"
    assert stored is not None
    assert stored.camera_id == UUID(original_id)
    assert stored.ipfs_cid == CID

    active = client.get("/cameras", headers=_auth(token))
    assert [item["id"] for item in active.json()["items"]] == [replacement_id]
    archived = client.get("/cameras/archived?q=lobby", headers=_auth(token))
    assert [item["id"] for item in archived.json()["items"]] == [original_id]


def test_restore_of_active_camera_is_conflict(client: TestClient) -> None:
    token = _register_and_token(client, "active@example.com")
    camera_id = str(_create(client, token, "Door", "rtsp://192.0.2.15/live")["id"])
    response = client.post(f"/cameras/{camera_id}/restore", headers=_auth(token))
    assert response.status_code == 409


def test_archived_list_is_owner_scoped_and_paged(client: TestClient) -> None:
    owner = _register_and_token(client, "pages@example.com")
    other = _register_and_token(client, "other-pages@example.com")
    first = str(_create(client, owner, "Alpha", "rtsp://192.0.2.16/a")["id"])
    second = str(_create(client, owner, "Beta", "rtsp://192.0.2.17/b")["id"])
    foreign = str(_create(client, other, "Foreign", "rtsp://192.0.2.18/c")["id"])
    for camera_id, token in ((first, owner), (second, owner), (foreign, other)):
        assert (
            client.post(
                f"/cameras/{camera_id}/archive", headers=_auth(token)
            ).status_code
            == 200
        )

    page = client.get(
        "/cameras/archived?page=1&page_size=1&sort=name_asc",
        headers=_auth(owner),
    )
    assert page.status_code == 200
    body = page.json()
    assert body["total"] == 2
    assert body["pages"] == 2
    assert [item["name"] for item in body["items"]] == ["Alpha"]

    nxt = client.get(
        "/cameras/archived?page=2&page_size=1&sort=name_asc",
        headers=_auth(owner),
    )
    assert [item["name"] for item in nxt.json()["items"]] == ["Beta"]

    hidden = client.get("/cameras/archived", headers=_auth(owner))
    assert foreign not in {item["id"] for item in hidden.json()["items"]}
    assert client.get("/cameras", headers=_auth(owner)).json()["total"] == 0


def test_other_user_cannot_archive_restore_or_read(
    client: TestClient, db_session: Session
) -> None:
    owner = _register_and_token(client, "owner-a@example.com")
    intruder = _register_and_token(client, "owner-b@example.com")
    camera_id = str(_create(client, owner, "Private", "rtsp://192.0.2.19/live")["id"])
    record = _add_recording(db_session, camera_id)

    for method, path in (
        ("post", f"/cameras/{camera_id}/archive"),
        ("post", f"/cameras/{camera_id}/restore"),
        ("get", f"/cameras/{camera_id}"),
        ("get", f"/cameras/{camera_id}/recordings"),
    ):
        response = client.request(method, path, headers=_auth(intruder))
        assert response.status_code == 404
        assert response.json()["detail"] == "Camera not found."

    assert (
        client.post(f"/cameras/{camera_id}/archive", headers=_auth(owner)).status_code
        == 200
    )
    for path in (
        f"/cameras/{camera_id}",
        f"/cameras/{camera_id}/recordings",
        f"/cameras/{camera_id}/recordings/{record.id}/playback",
        f"/cameras/{camera_id}/restore",
    ):
        response = client.request(
            "post" if path.endswith("/restore") else "get",
            path,
            headers=_auth(intruder),
        )
        assert response.status_code == 404

    listed = client.get("/cameras/archived", headers=_auth(intruder))
    assert listed.json()["total"] == 0
    db_session.expire_all()
    stored = db_session.get(VideoRecord, record.id)
    assert stored is not None and stored.camera_id == UUID(camera_id)


def test_archived_owner_can_play_and_download_verified_footage(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = _register_and_token(client, "watch@example.com")
    camera_id = str(_create(client, token, "Hall", "rtsp://192.0.2.20/live")["id"])
    record = _add_recording(db_session, camera_id)
    assert (
        client.post(f"/cameras/{camera_id}/archive", headers=_auth(token)).status_code
        == 200
    )

    fetched: list[str] = []

    def get_segment(
        checked_camera: UUID, started_at: datetime, **_kwargs: object
    ) -> SegmentAnchor:
        assert checked_camera == UUID(camera_id)
        return SegmentAnchor(
            camera_id=checked_camera,
            started_at=started_at,
            ended_at=record.ended_at,
            cid=record.ipfs_cid,
            segment_hash=record.segment_hash,
        )

    def fetch(cid: str, dest: Path, **_kwargs: object) -> None:
        fetched.append(cid)
        dest.write_bytes(VIDEO)

    monkeypatch.setattr(
        "app.services.recording_verification.get_segment",
        get_segment,
    )
    monkeypatch.setattr(
        "app.services.recording_verification.fetch_cid_to_file",
        fetch,
    )
    play_dir = tmp_path / "play"
    down_dir = tmp_path / "down"
    play_dir.mkdir()
    down_dir.mkdir()
    monkeypatch.setattr(
        "app.routers.recordings._playback_work_dir",
        lambda: play_dir,
    )
    monkeypatch.setattr(
        "app.routers.recordings._download_work_dir",
        lambda: down_dir,
    )

    played = client.get(
        f"/cameras/{camera_id}/recordings/{record.id}/playback",
        headers=_auth(token),
    )
    assert played.status_code == 200
    assert played.content == VIDEO
    assert fetched == [CID]

    downloaded = client.get(
        f"/cameras/{camera_id}/recordings/download",
        headers=_auth(token),
        params={
            "started_at": record.started_at.isoformat(),
            "ended_at": record.ended_at.isoformat(),
        },
    )
    assert downloaded.status_code == 200
    assert downloaded.headers["content-type"].startswith("multipart/form-data")
    assert CID.encode() in downloaded.content or VIDEO in downloaded.content
    assert fetched == [CID, CID]

    db_session.expire_all()
    stored = db_session.get(VideoRecord, record.id)
    assert stored is not None
    assert stored.camera_id == UUID(camera_id)
    assert stored.ipfs_cid == CID
    assert stored.tx_hash == TX


def test_unverified_archived_playback_returns_no_media(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = _register_and_token(client, "tamper@example.com")
    camera_id = str(_create(client, token, "Hall", "rtsp://192.0.2.21/live")["id"])
    record = _add_recording(db_session, camera_id)
    assert (
        client.post(f"/cameras/{camera_id}/archive", headers=_auth(token)).status_code
        == 200
    )
    work = tmp_path / "play"
    work.mkdir()
    monkeypatch.setattr("app.routers.recordings._playback_work_dir", lambda: work)

    def get_segment(
        checked_camera: UUID, started_at: datetime, **_kwargs: object
    ) -> SegmentAnchor:
        return SegmentAnchor(
            camera_id=checked_camera,
            started_at=started_at,
            ended_at=record.ended_at,
            cid="bafy-tampered",
            segment_hash=record.segment_hash,
        )

    monkeypatch.setattr(
        "app.services.recording_verification.get_segment",
        get_segment,
    )

    def fetch(_cid: str, dest: Path, **_kwargs: object) -> None:
        dest.write_bytes(VIDEO)

    monkeypatch.setattr(
        "app.services.recording_verification.fetch_cid_to_file",
        fetch,
    )

    response = client.get(
        f"/cameras/{camera_id}/recordings/{record.id}/playback",
        headers=_auth(token),
    )
    assert response.status_code == 409
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["overall"] == "tampered"
    assert VIDEO not in response.content


def test_archive_routes_require_auth(client: TestClient) -> None:
    camera_id = uuid4()
    assert client.get("/cameras/archived").status_code == 401
    assert client.post(f"/cameras/{camera_id}/archive").status_code == 401
    assert client.post(f"/cameras/{camera_id}/restore").status_code == 401
