"""Owner-scoped recording search API (Slice E / CP-E.P1–P2)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.deps import get_db
from app.main import app
from app.models.video_record import VideoRecord

import app.models as _models  # noqa: F401

TEST_PASSWORD = "test-password-12"
CID = "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi"
HASH = "aa" * 32
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
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
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
        json={
            "name": name,
            "stream_url": "rtsp://192.0.2.50/live",
        },
    )
    assert created.status_code == 201
    return created.json()["id"]


def _add_segment(
    db: Session,
    camera_id: str,
    started: datetime,
    *,
    cid: str = CID,
) -> VideoRecord:
    record = VideoRecord(
        id=uuid4(),
        camera_id=UUID(camera_id),
        started_at=started,
        ended_at=started + timedelta(seconds=60),
        ipfs_cid=cid,
        segment_hash=HASH,
        tx_hash=TX,
        created_at=datetime.now(timezone.utc),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def test_list_recordings_empty(client: TestClient) -> None:
    token = _register_and_token(client, "empty@example.com")
    camera_id = _create_camera(client, token)
    listed = client.get(
        f"/cameras/{camera_id}/recordings",
        headers=_auth_headers(token),
    )
    assert listed.status_code == 200
    assert listed.json() == {
        "items": [],
        "total": 0,
        "page": 1,
        "page_size": 10,
        "pages": 1,
    }


def test_recordings_require_auth(client: TestClient) -> None:
    response = client.get(f"/cameras/{uuid4()}/recordings")
    assert response.status_code == 401


def test_recordings_hidden_from_other_owner(client: TestClient, db_session: Session) -> None:
    token_a = _register_and_token(client, "owner-a@example.com")
    token_b = _register_and_token(client, "owner-b@example.com")
    camera_id = _create_camera(client, token_a)
    _add_segment(db_session, camera_id, NOON)

    forbidden = client.get(
        f"/cameras/{camera_id}/recordings",
        headers=_auth_headers(token_b),
    )
    assert forbidden.status_code == 404


def test_list_recordings_newest_first(client: TestClient, db_session: Session) -> None:
    token = _register_and_token(client, "lister@example.com")
    camera_id = _create_camera(client, token)
    first = _add_segment(db_session, camera_id, NOON)
    later = _add_segment(
        db_session,
        camera_id,
        NOON + timedelta(minutes=1),
        cid="bafybeih" + "a" * 50,
    )

    listed = client.get(
        f"/cameras/{camera_id}/recordings",
        headers=_auth_headers(token),
    )
    assert listed.status_code == 200
    body = listed.json()
    assert body["total"] == 2
    assert body["page"] == 1
    assert len(body["items"]) == 2
    assert body["items"][0]["id"] == str(later.id)
    assert body["items"][1]["id"] == str(first.id)
    assert body["items"][0]["ipfs_cid"] == later.ipfs_cid
    assert body["items"][0]["tx_hash"] == TX
    assert body["items"][0]["camera_id"] == camera_id


def test_list_recordings_filters_overlapping_window(
    client: TestClient, db_session: Session
) -> None:
    token = _register_and_token(client, "filter@example.com")
    camera_id = _create_camera(client, token)
    _add_segment(db_session, camera_id, NOON)
    _add_segment(db_session, camera_id, NOON + timedelta(hours=1))

    listed = client.get(
        f"/cameras/{camera_id}/recordings",
        headers=_auth_headers(token),
        params={
            "started_at": "2026-08-24T12:00:00Z",
            "ended_at": "2026-08-24T12:30:00Z",
        },
    )
    assert listed.status_code == 200
    body = listed.json()
    assert body["total"] == 1
    assert body["items"][0]["started_at"].startswith("2026-08-24T12:00:00")


def test_list_recordings_rejects_inverted_window(
    client: TestClient,
) -> None:
    token = _register_and_token(client, "window@example.com")
    camera_id = _create_camera(client, token)
    response = client.get(
        f"/cameras/{camera_id}/recordings",
        headers=_auth_headers(token),
        params={
            "started_at": "2026-08-24T13:00:00Z",
            "ended_at": "2026-08-24T12:00:00Z",
        },
    )
    assert response.status_code == 400


def test_list_recordings_unknown_camera(client: TestClient) -> None:
    token = _register_and_token(client, "missing@example.com")
    response = client.get(
        f"/cameras/{uuid4()}/recordings",
        headers=_auth_headers(token),
    )
    assert response.status_code == 404


def test_download_recordings_requires_auth(client: TestClient) -> None:
    response = client.get(
        f"/cameras/{uuid4()}/recordings/download",
        params={
            "started_at": "2026-08-24T12:00:00Z",
            "ended_at": "2026-08-24T12:05:00Z",
        },
    )
    assert response.status_code == 401


def test_download_recordings_hidden_from_other_owner(
    client: TestClient, db_session: Session
) -> None:
    token_a = _register_and_token(client, "dl-owner-a@example.com")
    token_b = _register_and_token(client, "dl-owner-b@example.com")
    camera_id = _create_camera(client, token_a)
    _add_segment(db_session, camera_id, NOON)

    forbidden = client.get(
        f"/cameras/{camera_id}/recordings/download",
        headers=_auth_headers(token_b),
        params={
            "started_at": "2026-08-24T12:00:00Z",
            "ended_at": "2026-08-24T12:05:00Z",
        },
    )
    assert forbidden.status_code == 404


def test_download_recordings_empty_range(client: TestClient) -> None:
    token = _register_and_token(client, "dl-empty@example.com")
    camera_id = _create_camera(client, token)
    response = client.get(
        f"/cameras/{camera_id}/recordings/download",
        headers=_auth_headers(token),
        params={
            "started_at": "2026-08-24T12:00:00Z",
            "ended_at": "2026-08-24T12:05:00Z",
        },
    )
    assert response.status_code == 404


def test_download_recordings_combines_range(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pathlib import Path

    from app.services import recording_download as download_mod

    def fake_assemble(cids: list[str], work_dir: Path, **_kwargs: object) -> Path:
        assert cids == [CID]
        output = work_dir / "combined.mp4"
        output.write_bytes(b"joined-mp4")
        return output

    monkeypatch.setattr(download_mod, "assemble_range_download", fake_assemble)
    monkeypatch.setattr(
        "app.routers.recordings.assemble_range_download", fake_assemble
    )

    token = _register_and_token(client, "dl-ok@example.com")
    camera_id = _create_camera(client, token)
    _add_segment(db_session, camera_id, NOON)

    response = client.get(
        f"/cameras/{camera_id}/recordings/download",
        headers=_auth_headers(token),
        params={
            "started_at": "2026-08-24T12:00:00Z",
            "ended_at": "2026-08-24T12:05:00Z",
        },
    )
    assert response.status_code == 200
    assert response.content == b"joined-mp4"
    assert "video/mp4" in response.headers.get("content-type", "")
    disposition = response.headers.get("content-disposition", "")
    assert "recordings_20260824T120000Z_20260824T120500Z.mp4" in disposition
