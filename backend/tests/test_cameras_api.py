"""Camera CRUD API tests (in-memory SQLite)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.deps import get_db
from app.main import app

import app.models  # noqa: F401

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

    other_list = client.get("/cameras", headers=_auth_headers(token_b))
    assert other_list.status_code == 200
    assert other_list.json()["total"] == 0

    listed = client.get("/cameras", headers=_auth_headers(token_a))
    assert listed.status_code == 200
    assert listed.json()["total"] == 1

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
