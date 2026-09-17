"""Owner-scoped verification attempt API (Slice E / CP-E.P8)."""

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


def _attempt_payload(
    *,
    record_id: str | None = None,
    overall: str = "verified",
    scope: str = "full",
    started_at: str = "2026-08-24T12:00:00Z",
    ended_at: str = "2026-08-24T12:01:00Z",
    minute_status: str | None = None,
) -> dict[str, object]:
    return {
        "started_at": started_at,
        "ended_at": ended_at,
        "scope": scope,
        "overall_status": overall,
        "minutes": [
            {
                "started_at": started_at,
                "status": minute_status or overall,
                "detail": "App CID, hash, and times match the blockchain record.",
                "video_record_id": record_id,
            }
        ],
    }


def test_create_attempt_requires_auth(client: TestClient) -> None:
    response = client.post(
        f"/cameras/{uuid4()}/verification-attempts",
        json=_attempt_payload(),
    )
    assert response.status_code == 401


def test_list_attempts_requires_auth(client: TestClient) -> None:
    response = client.get(f"/cameras/{uuid4()}/verification-attempts")
    assert response.status_code == 401


def test_attempts_hidden_from_other_owner(client: TestClient) -> None:
    token_a = _register_and_token(client, "owner-a@example.com")
    token_b = _register_and_token(client, "owner-b@example.com")
    camera_id = _create_camera(client, token_a)

    created = client.post(
        f"/cameras/{camera_id}/verification-attempts",
        headers=_auth_headers(token_a),
        json=_attempt_payload(),
    )
    assert created.status_code == 201

    forbidden_post = client.post(
        f"/cameras/{camera_id}/verification-attempts",
        headers=_auth_headers(token_b),
        json=_attempt_payload(),
    )
    assert forbidden_post.status_code == 404

    forbidden_get = client.get(
        f"/cameras/{camera_id}/verification-attempts",
        headers=_auth_headers(token_b),
    )
    assert forbidden_get.status_code == 404


def test_attempts_unknown_camera(client: TestClient) -> None:
    token = _register_and_token(client, "missing@example.com")
    response = client.post(
        f"/cameras/{uuid4()}/verification-attempts",
        headers=_auth_headers(token),
        json=_attempt_payload(),
    )
    assert response.status_code == 404


def test_create_attempt_persists_client_report(
    client: TestClient, db_session: Session
) -> None:
    token = _register_and_token(client, "audit@example.com")
    camera_id = _create_camera(client, token)
    segment = _add_segment(db_session, camera_id, NOON)

    created = client.post(
        f"/cameras/{camera_id}/verification-attempts",
        headers=_auth_headers(token),
        json=_attempt_payload(record_id=str(segment.id), scope="minute"),
    )
    assert created.status_code == 201
    body = created.json()
    assert body["camera_id"] == camera_id
    assert body["scope"] == "minute"
    assert body["overall_status"] == "verified"
    assert body["started_at"].startswith("2026-08-24T12:00:00")
    assert body["ended_at"].startswith("2026-08-24T12:01:00")
    assert len(body["minutes"]) == 1
    assert body["minutes"][0]["status"] == "verified"
    assert body["minutes"][0]["video_record_id"] == str(segment.id)
    assert body["user_id"]

    listed = client.get(
        f"/cameras/{camera_id}/verification-attempts",
        headers=_auth_headers(token),
    )
    assert listed.status_code == 200
    listing = listed.json()
    assert listing["total"] == 1
    assert listing["page"] == 1
    assert listing["page_size"] == 10
    assert listing["pages"] == 1
    assert "minutes" not in listing["items"][0]
    assert listing["items"][0]["id"] == body["id"]
    assert listing["items"][0]["overall_status"] == "verified"


def test_create_attempt_does_not_read_chain(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("audit persist must not read the chain")

    monkeypatch.setattr("app.services.chain_anchor.get_segment", boom)

    token = _register_and_token(client, "no-chain@example.com")
    camera_id = _create_camera(client, token)
    created = client.post(
        f"/cameras/{camera_id}/verification-attempts",
        headers=_auth_headers(token),
        json=_attempt_payload(overall="failed_to_verify"),
    )
    assert created.status_code == 201
    assert created.json()["overall_status"] == "failed_to_verify"


def test_create_attempt_rejects_inverted_window(client: TestClient) -> None:
    token = _register_and_token(client, "window@example.com")
    camera_id = _create_camera(client, token)
    response = client.post(
        f"/cameras/{camera_id}/verification-attempts",
        headers=_auth_headers(token),
        json=_attempt_payload(
            started_at="2026-08-24T13:00:00Z",
            ended_at="2026-08-24T12:00:00Z",
        ),
    )
    assert response.status_code == 400


def test_create_attempt_rejects_invalid_scope(client: TestClient) -> None:
    token = _register_and_token(client, "scope@example.com")
    camera_id = _create_camera(client, token)
    response = client.post(
        f"/cameras/{camera_id}/verification-attempts",
        headers=_auth_headers(token),
        json=_attempt_payload(scope="everything"),
    )
    assert response.status_code == 422


def test_create_attempt_rejects_empty_minutes(client: TestClient) -> None:
    token = _register_and_token(client, "empty-minutes@example.com")
    camera_id = _create_camera(client, token)
    payload = _attempt_payload()
    payload["minutes"] = []
    response = client.post(
        f"/cameras/{camera_id}/verification-attempts",
        headers=_auth_headers(token),
        json=payload,
    )
    assert response.status_code == 422


def test_list_attempts_newest_first(client: TestClient) -> None:
    token = _register_and_token(client, "order@example.com")
    camera_id = _create_camera(client, token)
    first = client.post(
        f"/cameras/{camera_id}/verification-attempts",
        headers=_auth_headers(token),
        json=_attempt_payload(overall="verified", scope="full"),
    )
    second = client.post(
        f"/cameras/{camera_id}/verification-attempts",
        headers=_auth_headers(token),
        json=_attempt_payload(overall="tampered", scope="partial"),
    )
    assert first.status_code == 201
    assert second.status_code == 201

    listed = client.get(
        f"/cameras/{camera_id}/verification-attempts",
        headers=_auth_headers(token),
        params={"page_size": 1},
    )
    assert listed.status_code == 200
    body = listed.json()
    assert body["total"] == 2
    assert body["pages"] == 2
    assert len(body["items"]) == 1
    assert body["items"][0]["id"] == second.json()["id"]
    assert body["items"][0]["overall_status"] == "tampered"

    page_two = client.get(
        f"/cameras/{camera_id}/verification-attempts",
        headers=_auth_headers(token),
        params={"page": 2, "page_size": 1},
    )
    assert page_two.status_code == 200
    assert page_two.json()["items"][0]["id"] == first.json()["id"]


def test_list_attempts_empty(client: TestClient) -> None:
    token = _register_and_token(client, "empty@example.com")
    camera_id = _create_camera(client, token)
    listed = client.get(
        f"/cameras/{camera_id}/verification-attempts",
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
