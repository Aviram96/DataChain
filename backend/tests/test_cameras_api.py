"""Camera CRUD API tests (in-memory SQLite)."""

from __future__ import annotations

from datetime import datetime, timezone
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

import app.models as _models  # noqa: F401

TEST_PASSWORD = "test-password-12"


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


def test_camera_crud_owner_scoped(client: TestClient) -> None:
    token_a = _register_and_token(client, "owner-a@example.com")
    token_b = _register_and_token(client, "owner-b@example.com")

    create = client.post(
        "/cameras",
        headers=_auth_headers(token_a),
        json={
            "name": "Front door",
            "stream_url": "rtsp://192.0.2.1/stream1",
            "location": "Lobby",
        },
    )
    assert create.status_code == 201
    body = create.json()
    camera_id = body["id"]
    assert body["name"] == "Front door"
    assert body["location"] == "Lobby"
    assert body["status"] == "offline"
    assert body["offline_reason"] == "unreachable"
    assert body["ingest_offline_at"] is None

    other_list = client.get("/cameras", headers=_auth_headers(token_b))
    assert other_list.status_code == 200
    assert other_list.json()["total"] == 0

    listed = client.get("/cameras", headers=_auth_headers(token_a))
    assert listed.status_code == 200
    listed_body = listed.json()
    assert listed_body["total"] == 1
    assert listed_body["items"][0]["status"] == "offline"
    assert listed_body["items"][0]["offline_reason"] == "unreachable"
    assert listed_body["items"][0]["ingest_offline_at"] is None

    get_one = client.get(
        f"/cameras/{camera_id}",
        headers=_auth_headers(token_a),
    )
    assert get_one.status_code == 200

    forbidden = client.get(
        f"/cameras/{camera_id}",
        headers=_auth_headers(token_b),
    )
    assert forbidden.status_code == 404

    updated = client.patch(
        f"/cameras/{camera_id}",
        headers=_auth_headers(token_a),
        json={"name": "Front entrance"},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Front entrance"

    deleted = client.delete(
        f"/cameras/{camera_id}",
        headers=_auth_headers(token_a),
    )
    assert deleted.status_code == 204

    missing = client.get(
        f"/cameras/{camera_id}",
        headers=_auth_headers(token_a),
    )
    assert missing.status_code == 404


def test_cameras_require_auth(client: TestClient) -> None:
    response = client.get("/cameras")
    assert response.status_code == 401


def test_invalid_stream_url_rejected(client: TestClient) -> None:
    token = _register_and_token(client, "validator@example.com")
    response = client.post(
        "/cameras",
        headers=_auth_headers(token),
        json={
            "name": "Bad URL",
            "stream_url": "ftp://example.com/v",
        },
    )
    assert response.status_code == 422


def test_list_pagination(client: TestClient) -> None:
    token = _register_and_token(client, "pager@example.com")
    headers = _auth_headers(token)

    for index in range(12):
        response = client.post(
            "/cameras",
            headers=headers,
            json={
                "name": f"Cam {index}",
                "stream_url": f"http://192.0.2.{index}/live",
            },
        )
        assert response.status_code == 201

    page1 = client.get("/cameras?page=1&page_size=10", headers=headers)
    assert page1.status_code == 200
    data = page1.json()
    assert data["total"] == 12
    assert len(data["items"]) == 10
    assert data["pages"] == 2

    page2 = client.get("/cameras?page=2&page_size=10", headers=headers)
    assert page2.status_code == 200
    assert len(page2.json()["items"]) == 2


def test_get_camera_not_found(client: TestClient) -> None:
    token = _register_and_token(client, "missing@example.com")
    response = client.get(
        f"/cameras/{uuid4()}",
        headers=_auth_headers(token),
    )
    assert response.status_code == 404


def test_duplicate_camera_name_rejected(client: TestClient) -> None:
    token = _register_and_token(client, "unique-name@example.com")
    headers = _auth_headers(token)
    first = client.post(
        "/cameras",
        headers=headers,
        json={"name": "Lobby", "stream_url": "http://192.0.2.10/live"},
    )
    assert first.status_code == 201

    duplicate = client.post(
        "/cameras",
        headers=headers,
        json={"name": "lobby", "stream_url": "http://192.0.2.11/live"},
    )
    assert duplicate.status_code == 409
    assert "already have a camera" in duplicate.json()["detail"].lower()


def test_soft_delete_hides_camera_but_keeps_row(
    client: TestClient, db_session: Session
) -> None:
    from uuid import UUID

    from app.models.camera import Camera

    token = _register_and_token(client, "soft-delete@example.com")
    headers = _auth_headers(token)
    created = client.post(
        "/cameras",
        headers=headers,
        json={"name": "Yard", "stream_url": "rtsp://192.0.2.20/stream"},
    )
    assert created.status_code == 201
    camera_id = created.json()["id"]

    deleted = client.delete(f"/cameras/{camera_id}", headers=headers)
    assert deleted.status_code == 204

    listed = client.get("/cameras", headers=headers)
    assert listed.status_code == 200
    assert listed.json()["total"] == 0

    missing = client.get(f"/cameras/{camera_id}", headers=headers)
    assert missing.status_code == 404

    db_session.expire_all()
    row = db_session.get(Camera, UUID(camera_id))
    assert row is not None
    assert row.deleted_at is not None

    # Soft-deleted name can be reused for a new active camera.
    again = client.post(
        "/cameras",
        headers=headers,
        json={"name": "Yard", "stream_url": "rtsp://192.0.2.21/stream"},
    )
    assert again.status_code == 201


def test_list_search_sort_and_status_filter(client: TestClient) -> None:
    token = _register_and_token(client, "filters@example.com")
    headers = _auth_headers(token)

    for name, url in (
        ("Alpha Gate", "http://192.0.2.1/a"),
        ("Beta Gate", "http://192.0.2.2/b"),
        ("Yard Cam", "http://192.0.2.3/c"),
    ):
        response = client.post(
            "/cameras",
            headers=headers,
            json={"name": name, "stream_url": url},
        )
        assert response.status_code == 201

    search = client.get("/cameras?q=gate&sort=name_asc", headers=headers)
    assert search.status_code == 200
    names = [item["name"] for item in search.json()["items"]]
    assert names == ["Alpha Gate", "Beta Gate"]

    # Stub probe marks everything offline — status=offline returns all matches.
    offline = client.get("/cameras?status=offline&sort=name_desc", headers=headers)
    assert offline.status_code == 200
    assert offline.json()["total"] == 3
    assert offline.json()["items"][0]["name"] == "Yard Cam"

    online = client.get("/cameras?status=online", headers=headers)
    assert online.status_code == 200
    assert online.json()["total"] == 0


def test_ingest_offline_overrides_live_probe(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.routers.cameras.probe_status",
        lambda _url: "online",
    )
    monkeypatch.setattr(
        "app.routers.cameras.probe_many_statuses",
        lambda urls: ["online"] * len(urls),
    )
    token = _register_and_token(client, "ingest-offline@example.com")
    headers = _auth_headers(token)
    created = client.post(
        "/cameras",
        headers=headers,
        json={"name": "Gate", "stream_url": "rtsp://192.0.2.40/live"},
    )
    assert created.status_code == 201
    camera_id = created.json()["id"]
    assert created.json()["status"] == "online"
    assert created.json()["offline_reason"] is None
    assert created.json()["ingest_offline_at"] is None

    camera = db_session.get(Camera, UUID(camera_id))
    assert camera is not None
    marked_at = datetime.now(timezone.utc)
    camera.ingest_offline_at = marked_at
    db_session.commit()

    detail = client.get(f"/cameras/{camera_id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["status"] == "offline"
    assert detail.json()["offline_reason"] == "ingest_failed"
    raw_offline_at = detail.json()["ingest_offline_at"]
    assert raw_offline_at
    returned_at = datetime.fromisoformat(str(raw_offline_at).replace("Z", "+00:00"))
    if returned_at.tzinfo is None:
        returned_at = returned_at.replace(tzinfo=timezone.utc)
    assert abs((returned_at - marked_at).total_seconds()) < 1

    listed = client.get("/cameras?status=offline", headers=headers)
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["offline_reason"] == "ingest_failed"
    assert listed.json()["items"][0]["ingest_offline_at"] is not None

