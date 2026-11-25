"""Two-user authorization for cameras, recordings, playback, and history.

Uses the in-memory SQLite TestClient. Blockchain and IPFS helpers are
replaced so an unauthorized request fails if it reaches either one.
"""

from __future__ import annotations

from dataclasses import dataclass
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
CID_A = "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi"
CID_B = "bafybeih" + "b" * 50
HASH = "aa" * 32
TX = "0x" + "bb" * 32
NOON = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
CAMERA_A_NAME = "Alpha lobby"
CAMERA_B_NAME = "Beta gate"


@dataclass(frozen=True)
class TwoUsers:
    token_a: str
    token_b: str
    camera_a: str
    camera_b: str
    record_a: VideoRecord
    record_b: VideoRecord


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


@pytest.fixture
def chain_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Fail the test if verification reads the chain or downloads from IPFS."""
    calls: list[str] = []

    def forbid(kind: str):
        def _forbid(*_args: object, **_kwargs: object) -> None:
            calls.append(kind)
            raise AssertionError(
                "Ownership check did not run before blockchain or IPFS access."
            )

        return _forbid

    monkeypatch.setattr(
        "app.services.recording_verification.get_segment",
        forbid("blockchain"),
    )
    monkeypatch.setattr(
        "app.services.chain_anchor.get_segment",
        forbid("blockchain"),
    )
    monkeypatch.setattr(
        "app.services.recording_verification.fetch_cid_to_file",
        forbid("ipfs"),
    )
    monkeypatch.setattr(
        "app.services.recording_download.fetch_cid_to_file",
        forbid("ipfs"),
    )
    return calls


@pytest.fixture
def users(client: TestClient, db_session: Session) -> TwoUsers:
    token_a = _register_and_token(client, "owner-a@example.com")
    token_b = _register_and_token(client, "owner-b@example.com")
    camera_a = _create_camera(client, token_a, CAMERA_A_NAME, "Lobby")
    camera_b = _create_camera(client, token_b, CAMERA_B_NAME, "Gate")
    record_a = _add_segment(db_session, camera_a, NOON, cid=CID_A)
    record_b = _add_segment(
        db_session,
        camera_b,
        NOON + timedelta(hours=1),
        cid=CID_B,
    )
    return TwoUsers(
        token_a=token_a,
        token_b=token_b,
        camera_a=camera_a,
        camera_b=camera_b,
        record_a=record_a,
        record_b=record_b,
    )


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
    token = login.json()["access_token"]
    assert token != ""
    return token


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_camera(
    client: TestClient,
    token: str,
    name: str,
    location: str,
) -> str:
    created = client.post(
        "/cameras",
        headers=_auth_headers(token),
        json={
            "name": name,
            "stream_url": "rtsp://192.0.2.50/live",
            "location": location,
        },
    )
    assert created.status_code == 201
    return created.json()["id"]


def _add_segment(
    db: Session,
    camera_id: str,
    started: datetime,
    *,
    cid: str,
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


def _attempt_payload(record_id: UUID) -> dict[str, object]:
    started = NOON.isoformat().replace("+00:00", "Z")
    ended = (NOON + timedelta(seconds=60)).isoformat().replace("+00:00", "Z")
    return {
        "started_at": started,
        "ended_at": ended,
        "scope": "minute",
        "overall_status": "verified",
        "minutes": [
            {
                "started_at": started,
                "status": "verified",
                "detail": "Stored CID matches the blockchain record.",
                "video_record_id": str(record_id),
            }
        ],
    }


def _download_params(started: datetime, ended: datetime) -> dict[str, str]:
    return {
        "started_at": started.isoformat(),
        "ended_at": ended.isoformat(),
    }


def _assert_unauthorized(response) -> None:
    assert response.status_code == 401
    assert response.json()["detail"] == "Not authenticated."


def _assert_camera_hidden(response) -> None:
    assert response.status_code == 404
    assert response.json()["detail"] == "Camera not found."


def _assert_recording_hidden(response) -> None:
    assert response.status_code == 404
    assert response.json()["detail"] == "Recording not found."


def test_unauthenticated_requests_return_401(
    client: TestClient,
    users: TwoUsers,
    chain_calls: list[str],
) -> None:
    camera_id = users.camera_a
    record_id = users.record_a.id
    download = _download_params(NOON, NOON + timedelta(minutes=5))
    routes = [
        ("get", f"/cameras/{camera_id}", None),
        ("get", "/cameras", None),
        ("patch", f"/cameras/{camera_id}", {"name": "Taken"}),
        ("delete", f"/cameras/{camera_id}", None),
        ("get", f"/cameras/{camera_id}/recordings", None),
        ("get", f"/cameras/{camera_id}/recordings/{record_id}/playback", None),
        ("get", f"/cameras/{camera_id}/recordings/download", download),
        ("get", f"/cameras/{camera_id}/verification-attempts", None),
        (
            "post",
            f"/cameras/{camera_id}/verification-attempts",
            _attempt_payload(record_id),
        ),
    ]
    for method, path, payload in routes:
        if method == "get":
            response = client.get(path, params=payload)
        elif method == "patch":
            response = client.patch(path, json=payload)
        elif method == "delete":
            response = client.delete(path)
        else:
            response = client.post(path, json=payload)
        _assert_unauthorized(response)
    assert chain_calls == []


def test_other_user_cannot_read_update_or_delete_camera(
    client: TestClient,
    users: TwoUsers,
    chain_calls: list[str],
) -> None:
    headers = _auth_headers(users.token_b)

    _assert_camera_hidden(client.get(f"/cameras/{users.camera_a}", headers=headers))
    _assert_camera_hidden(
        client.patch(
            f"/cameras/{users.camera_a}",
            headers=headers,
            json={"name": "Stolen name", "location": "Stolen location"},
        )
    )
    _assert_camera_hidden(client.delete(f"/cameras/{users.camera_a}", headers=headers))
    assert chain_calls == []


def test_other_user_cannot_list_play_or_download_recordings(
    client: TestClient,
    users: TwoUsers,
    chain_calls: list[str],
) -> None:
    headers = _auth_headers(users.token_b)
    camera_id = users.camera_a
    record = users.record_a

    _assert_camera_hidden(
        client.get(
            f"/cameras/{camera_id}/recordings",
            headers=headers,
            params=_download_params(NOON, NOON + timedelta(minutes=5)),
        )
    )
    _assert_camera_hidden(
        client.get(
            f"/cameras/{camera_id}/recordings/{record.id}/playback",
            headers=headers,
        )
    )
    windows = [
        (record.started_at, record.ended_at),
        (NOON + timedelta(seconds=10), NOON + timedelta(seconds=40)),
        (NOON, NOON + timedelta(minutes=5)),
    ]
    for started, ended in windows:
        _assert_camera_hidden(
            client.get(
                f"/cameras/{camera_id}/recordings/download",
                headers=headers,
                params=_download_params(started, ended),
            )
        )
    assert chain_calls == []


def test_recording_id_is_not_reachable_through_the_other_camera(
    client: TestClient,
    users: TwoUsers,
    chain_calls: list[str],
) -> None:
    headers = _auth_headers(users.token_b)
    response = client.get(
        f"/cameras/{users.camera_b}/recordings/{users.record_a.id}/playback",
        headers=headers,
    )
    _assert_recording_hidden(response)

    listed = client.get(
        f"/cameras/{users.camera_b}/recordings",
        headers=headers,
    )
    assert listed.status_code == 200
    body = listed.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == str(users.record_b.id)
    assert body["items"][0]["ipfs_cid"] == CID_B
    assert CID_A not in listed.text
    assert chain_calls == []


def test_camera_list_returns_only_the_authenticated_user(
    client: TestClient,
    users: TwoUsers,
    chain_calls: list[str],
) -> None:
    listed_a = client.get("/cameras", headers=_auth_headers(users.token_a))
    assert listed_a.status_code == 200
    body_a = listed_a.json()
    assert body_a["total"] == 1
    assert [item["id"] for item in body_a["items"]] == [users.camera_a]
    assert body_a["items"][0]["name"] == CAMERA_A_NAME

    listed_b = client.get("/cameras", headers=_auth_headers(users.token_b))
    assert listed_b.status_code == 200
    body_b = listed_b.json()
    assert body_b["total"] == 1
    assert [item["id"] for item in body_b["items"]] == [users.camera_b]

    hidden = client.get(
        "/cameras",
        headers=_auth_headers(users.token_b),
        params={"q": CAMERA_A_NAME},
    )
    assert hidden.status_code == 200
    assert hidden.json()["total"] == 0
    assert hidden.json()["items"] == []
    assert chain_calls == []


def test_other_user_cannot_read_or_create_verification_history(
    client: TestClient,
    users: TwoUsers,
    chain_calls: list[str],
) -> None:
    headers = _auth_headers(users.token_b)
    _assert_camera_hidden(
        client.get(
            f"/cameras/{users.camera_a}/verification-attempts",
            headers=headers,
        )
    )
    _assert_camera_hidden(
        client.post(
            f"/cameras/{users.camera_a}/verification-attempts",
            headers=headers,
            json=_attempt_payload(users.record_a.id),
        )
    )
    assert chain_calls == []


def test_owner_keeps_access_after_unauthorized_requests(
    client: TestClient,
    users: TwoUsers,
    chain_calls: list[str],
) -> None:
    intruder = _auth_headers(users.token_b)
    camera_id = users.camera_a
    record = users.record_a

    _assert_camera_hidden(client.get(f"/cameras/{camera_id}", headers=intruder))
    _assert_camera_hidden(
        client.patch(
            f"/cameras/{camera_id}",
            headers=intruder,
            json={"name": "Stolen name"},
        )
    )
    _assert_camera_hidden(client.delete(f"/cameras/{camera_id}", headers=intruder))
    _assert_camera_hidden(
        client.get(f"/cameras/{camera_id}/recordings", headers=intruder)
    )
    _assert_camera_hidden(
        client.get(
            f"/cameras/{camera_id}/recordings/{record.id}/playback",
            headers=intruder,
        )
    )
    _assert_camera_hidden(
        client.get(
            f"/cameras/{camera_id}/recordings/download",
            headers=intruder,
            params=_download_params(record.started_at, record.ended_at),
        )
    )
    _assert_camera_hidden(
        client.get(
            f"/cameras/{camera_id}/verification-attempts",
            headers=intruder,
        )
    )
    _assert_camera_hidden(
        client.post(
            f"/cameras/{camera_id}/verification-attempts",
            headers=intruder,
            json=_attempt_payload(record.id),
        )
    )
    _assert_recording_hidden(
        client.get(
            f"/cameras/{users.camera_b}/recordings/{record.id}/playback",
            headers=intruder,
        )
    )
    assert chain_calls == []

    owner = _auth_headers(users.token_a)
    camera = client.get(f"/cameras/{camera_id}", headers=owner)
    assert camera.status_code == 200
    assert camera.json()["name"] == CAMERA_A_NAME
    assert camera.json()["location"] == "Lobby"

    listed = client.get("/cameras", headers=owner)
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["items"]] == [camera_id]

    recordings = client.get(f"/cameras/{camera_id}/recordings", headers=owner)
    assert recordings.status_code == 200
    body = recordings.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == str(record.id)
    assert body["items"][0]["ipfs_cid"] == CID_A
    assert body["items"][0]["camera_id"] == camera_id

    history = client.get(
        f"/cameras/{camera_id}/verification-attempts",
        headers=owner,
    )
    assert history.status_code == 200
    assert history.json()["total"] == 0
    assert chain_calls == []
