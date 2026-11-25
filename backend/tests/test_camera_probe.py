"""Unit tests for camera stream reachability probe."""

from __future__ import annotations

import urllib.error
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.deps import get_db
from app.main import app

import app.models as _models  # noqa: F401

from app.services.camera_probe import (
    probe_many_statuses,
    probe_status,
    probe_stream_reachable,
    resolve_stream_host_port,
)


def test_resolve_stream_host_port_defaults() -> None:
    assert resolve_stream_host_port("http://cam.local/live") == ("cam.local", 80)
    assert resolve_stream_host_port("https://cam.local:8443/v") == (
        "cam.local",
        8443,
    )
    assert resolve_stream_host_port("rtsp://10.0.0.5/stream") == ("10.0.0.5", 554)


def test_resolve_stream_host_port_invalid() -> None:
    assert resolve_stream_host_port("ftp://example.com/v") is None
    assert resolve_stream_host_port("not-a-url") is None


def test_probe_http_reachable_on_response() -> None:
    mock_response = MagicMock()
    mock_response.read.return_value = b""
    mock_response.__enter__.return_value = mock_response
    with patch(
        "app.services.camera_probe.urllib.request.urlopen",
        return_value=mock_response,
    ):
        assert probe_stream_reachable("http://192.0.2.1/live", timeout=1.0) is True


def test_probe_http_reachable_on_http_error() -> None:
    from email.message import EmailMessage

    with patch(
        "app.services.camera_probe.urllib.request.urlopen",
        side_effect=urllib.error.HTTPError(
            "http://192.0.2.1/live",
            401,
            "Unauthorized",
            EmailMessage(),
            None,
        ),
    ):
        assert probe_stream_reachable("http://192.0.2.1/live", timeout=1.0) is True


def test_probe_http_unreachable() -> None:
    with patch(
        "app.services.camera_probe.urllib.request.urlopen",
        side_effect=urllib.error.URLError("down"),
    ):
        assert probe_stream_reachable("http://192.0.2.1/live", timeout=1.0) is False


RTSP_URL = "rtsp://192.0.2.2:8554/camera1"


def _rtsp_socket(chunks: list[bytes] | Exception) -> MagicMock:
    sock = MagicMock()
    if isinstance(chunks, Exception):
        sock.recv.side_effect = chunks
    else:
        sock.recv.side_effect = [*chunks, b""]
    return sock


def _describe(chunks: list[bytes] | Exception, *, url: str = RTSP_URL):
    sock = _rtsp_socket(chunks)
    with patch("app.services.camera_probe.socket.create_connection") as connect:
        connect.return_value.__enter__.return_value = sock
        result = probe_stream_reachable(url, timeout=1.0)
    sent = b"".join(call.args[0] for call in sock.sendall.call_args_list)
    return result, sent, connect


def test_describe_uses_the_complete_rtsp_url() -> None:
    online, sent, connect = _describe([b"RTSP/1.0 200 OK\r\nCSeq: 1\r\n\r\n"])

    assert online is True
    assert b"DESCRIBE rtsp://192.0.2.2:8554/camera1 RTSP/1.0\r\n" in sent
    assert b"OPTIONS" not in sent
    assert connect.call_args.args == (("192.0.2.2", 8554),)
    assert connect.call_args.kwargs["timeout"] == 1.0


def test_describe_200_is_online() -> None:
    online, _sent, _connect = _describe([b"RTSP/1.0 ", b"200 OK\r\nCSeq: 1\r\n\r\n"])
    assert online is True
    sock = _rtsp_socket([b"RTSP/1.0 200 OK\r\n\r\n"])
    with patch("app.services.camera_probe.socket.create_connection") as connect:
        connect.return_value.__enter__.return_value = sock
        assert probe_status(RTSP_URL) == "online"


def test_describe_404_is_offline_even_when_tcp_connects() -> None:
    offline, sent, connect = _describe([b"RTSP/1.0 404 Not Found\r\nCSeq: 1\r\n\r\n"])

    assert offline is False
    assert connect.called
    assert b"DESCRIBE rtsp://192.0.2.2:8554/camera1 RTSP/1.0\r\n" in sent


def test_describe_401_and_other_non_200_are_offline() -> None:
    for body in (
        b"RTSP/1.0 401 Unauthorized\r\n\r\n",
        b"RTSP/1.0 500 Server Error\r\n\r\n",
        b"RTSP/1.0 2000 OK\r\n\r\n",
    ):
        reachable, _sent, _connect = _describe([body])
        assert reachable is False


def test_describe_timeout_is_offline() -> None:
    reachable, _sent, _connect = _describe(TimeoutError("timed out"))
    assert reachable is False


def test_describe_connection_refusal_is_offline() -> None:
    with patch(
        "app.services.camera_probe.socket.create_connection",
        side_effect=ConnectionRefusedError("refused"),
    ):
        assert probe_stream_reachable(RTSP_URL, timeout=1.0) is False
        assert probe_status(RTSP_URL) == "offline"


def test_describe_empty_or_malformed_response_is_offline() -> None:
    for chunks in (
        [b""],
        [b"\r\n"],
        [b"HTTP/1.1 200 OK\r\n\r\n"],
        [b"RTSP/1.0\r\n"],
        [b"\xff\xfe not ascii\r\n"],
    ):
        reachable, _sent, _connect = _describe(chunks)
        assert reachable is False


def test_probe_status_and_many() -> None:
    with patch(
        "app.services.camera_probe.probe_stream_reachable",
        return_value=True,
    ):
        assert probe_status("http://a") == "online"

    statuses = {
        "http://a": "online",
        "http://b": "offline",
    }
    with patch(
        "app.services.camera_probe.probe_status",
        side_effect=lambda url: statuses[url],
    ):
        assert probe_many_statuses(["http://a", "http://b"]) == ["online", "offline"]


def test_archived_cameras_are_not_probed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = factory()

    def override_get_db():
        try:
            yield db
        finally:
            pass

    calls: list[str] = []

    def allow_probe(url: str) -> str:
        calls.append(url)
        return "offline"

    def allow_many(urls: list[str]) -> list[str]:
        calls.extend(urls)
        return ["offline"] * len(urls)

    def forbid_probe(*_args: object, **_kwargs: object) -> None:
        calls.append("probed")
        raise AssertionError("archived cameras must not be probed")

    monkeypatch.setattr("app.routers.cameras.probe_status", allow_probe)
    monkeypatch.setattr("app.routers.cameras.probe_many_statuses", allow_many)
    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            registered = client.post(
                "/auth/register",
                json={
                    "email": "probe-archive@example.com",
                    "password": "test-password-12",
                },
            )
            assert registered.status_code == 201
            login = client.post(
                "/auth/login",
                json={
                    "email": "probe-archive@example.com",
                    "password": "test-password-12",
                },
            )
            assert login.status_code == 200
            token = login.json()["access_token"]
            headers = {"Authorization": f"Bearer {token}"}
            created = client.post(
                "/cameras",
                headers=headers,
                json={
                    "name": "Archived probe",
                    "stream_url": "rtsp://192.0.2.2:8554/camera1",
                },
            )
            assert created.status_code == 201
            camera_id = created.json()["id"]
            calls.clear()
            monkeypatch.setattr("app.routers.cameras.probe_status", forbid_probe)
            monkeypatch.setattr(
                "app.routers.cameras.probe_many_statuses",
                forbid_probe,
            )
            archived = client.post(
                f"/cameras/{camera_id}/archive",
                headers=headers,
            )
            assert archived.status_code == 200
            listed = client.get("/cameras/archived", headers=headers)
            detail = client.get(f"/cameras/{camera_id}", headers=headers)
        assert listed.status_code == 200
        assert listed.json()["items"][0]["lifecycle"] == "archived"
        assert listed.json()["items"][0]["status"] == "offline"
        assert detail.status_code == 200
        assert detail.json()["lifecycle"] == "archived"
        assert detail.json()["status"] == "offline"
        assert calls == []
    finally:
        app.dependency_overrides.clear()
        db.close()
        Base.metadata.drop_all(bind=engine)
