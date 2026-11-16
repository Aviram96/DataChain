"""Download serves a file only after backend range verification."""

from __future__ import annotations

import hashlib
import json
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
from app.routers.recordings import _VerifiedDownloadResponse
from app.services.chain_anchor import ChainAnchorError, SegmentAnchor
from app.services.recording_download import RecordingDownloadError

import app.models as _models  # noqa: F401

TEST_PASSWORD = "test-password-12"
TX = "0x" + "cc" * 32
NOON = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
VIDEO = b"verified-download-bytes"
POISON = b"should-not-ship"


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
    body: bytes = VIDEO,
    seconds: int = 60,
    cid: str | None = None,
) -> VideoRecord:
    record = VideoRecord(
        id=uuid4(),
        camera_id=UUID(camera_id),
        started_at=started,
        ended_at=started + timedelta(seconds=seconds),
        ipfs_cid=cid or f"bafy{uuid4().hex}",
        segment_hash=hashlib.sha256(body).hexdigest(),
        tx_hash=TX,
        created_at=datetime.now(timezone.utc),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def _pin_work_dir(monkeypatch: pytest.MonkeyPatch, work: Path) -> None:
    work.mkdir()
    monkeypatch.setattr("app.routers.recordings._download_work_dir", lambda: work)


def _unix(moment: datetime) -> int:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return int(moment.timestamp())


def _install_sources(
    monkeypatch: pytest.MonkeyPatch,
    records: list[VideoRecord],
    modes: dict[UUID, str],
    *,
    bodies: dict[UUID, bytes],
    fetched: list[str],
) -> None:
    by_cid = {record.ipfs_cid: record for record in records}
    by_start = {_unix(record.started_at): record for record in records}

    def get_segment(
        camera_id: UUID, started_at: datetime, **_kwargs: object
    ) -> SegmentAnchor:
        record = by_start[_unix(started_at)]
        mode = modes[record.id]
        if mode == "missing":
            raise ChainAnchorError("AnchorNotFound")
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
        record = by_cid[cid]
        mode = modes[record.id]
        if mode == "unavailable":
            dest.write_bytes(POISON)
            raise RecordingDownloadError("Could not retrieve a segment from IPFS.")
        if mode == "hash_mismatch":
            dest.write_bytes(b"tampered-bytes")
            return
        dest.write_bytes(bodies[record.id])

    monkeypatch.setattr(
        "app.services.recording_verification.get_segment",
        get_segment,
    )
    monkeypatch.setattr(
        "app.services.recording_verification.fetch_cid_to_file",
        fetch,
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


def _multipart(response) -> tuple[dict[str, object], bytes]:
    assert response.status_code == 200
    header = response.headers["content-type"]
    assert header.startswith("multipart/form-data")
    boundary = header.split("boundary=", 1)[1].strip().strip('"')
    marker = ("--" + boundary).encode()
    report = None
    video = None
    for section in response.content.split(marker):
        if b'name="report"' in section:
            raw = section.split(b"\r\n\r\n", 1)[1].strip()
            report = json.loads(raw)
        elif b'name="video"' in section:
            video = section.split(b"\r\n\r\n", 1)[1]
            if video.endswith(b"\r\n"):
                video = video[:-2]
    assert isinstance(report, dict)
    assert isinstance(video, bytes)
    return report, video


def test_download_requires_auth(client: TestClient) -> None:
    response = client.get(
        f"/cameras/{uuid4()}/recordings/download",
        params={
            "started_at": "2026-08-24T12:00:00Z",
            "ended_at": "2026-08-24T12:01:00Z",
        },
    )
    assert response.status_code == 401


def test_download_hidden_from_other_owner(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token_a = _register_and_token(client, "dl-owner-a@example.com")
    token_b = _register_and_token(client, "dl-owner-b@example.com")
    camera_id = _create_camera(client, token_a)
    _add_segment(db_session, camera_id, NOON)

    def forbid(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("verification must not run for another owner")

    monkeypatch.setattr(
        "app.services.recording_verification.get_segment",
        forbid,
    )
    response = _download(
        client,
        token_b,
        camera_id,
        NOON,
        NOON + timedelta(seconds=60),
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Camera not found."


def test_full_success_returns_verified_file_and_report(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = _register_and_token(client, "dl-verified@example.com")
    camera_id = _create_camera(client, token)
    record = _add_segment(db_session, camera_id, NOON)
    work = tmp_path / "download-work"
    _pin_work_dir(monkeypatch, work)
    fetched: list[str] = []
    _install_sources(
        monkeypatch,
        [record],
        {record.id: "verified"},
        bodies={record.id: VIDEO},
        fetched=fetched,
    )

    response = _download(client, token, camera_id, NOON, record.ended_at)
    report, video = _multipart(response)

    assert video == VIDEO
    assert fetched == [record.ipfs_cid]
    assert report["overall"] == "verified"
    assert report["discontinuous"] is False
    assert report["detail"] == "Every segment in this range is verified."
    assert report["segments"][0]["status"] == "verified"
    assert report["segments"][0]["video_record_id"] == str(record.id)
    assert report["segments"][0]["tx_hash"] == TX
    assert report["missing_intervals"] == []
    assert report["excluded_intervals"] == []
    assert str(work) not in response.text
    assert b"work_dir" not in response.content
    assert response.headers["cache-control"] == "no-store"
    assert not work.exists()


def test_two_verified_segments_are_concatenated_in_order(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = _register_and_token(client, "dl-two@example.com")
    camera_id = _create_camera(client, token)
    first_body = b"seg-a"
    second_body = b"seg-b"
    first = _add_segment(db_session, camera_id, NOON, body=first_body)
    second = _add_segment(
        db_session,
        camera_id,
        NOON + timedelta(seconds=60),
        body=second_body,
    )
    work = tmp_path / "download-work"
    _pin_work_dir(monkeypatch, work)
    seen: list[list[bytes]] = []

    def concat(paths: list[Path], output: Path) -> None:
        seen.append([path.read_bytes() for path in paths])
        output.write_bytes(b"joined")

    monkeypatch.setattr("app.services.recording_download.concat_mp4s", concat)
    _install_sources(
        monkeypatch,
        [first, second],
        {first.id: "verified", second.id: "verified"},
        bodies={first.id: first_body, second.id: second_body},
        fetched=[],
    )

    response = _download(
        client,
        token,
        camera_id,
        NOON,
        second.ended_at,
    )
    report, video = _multipart(response)

    assert seen == [[first_body, second_body]]
    assert video == b"joined"
    assert report["overall"] == "verified"
    assert report["discontinuous"] is False
    assert [item["status"] for item in report["segments"]] == ["verified", "verified"]
    assert not work.exists()


def test_partial_success_omits_unverified_segments(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = _register_and_token(client, "dl-partial@example.com")
    camera_id = _create_camera(client, token)
    first_body = b"keep-a"
    third_body = b"keep-c"
    first = _add_segment(db_session, camera_id, NOON, body=first_body)
    middle = _add_segment(
        db_session,
        camera_id,
        NOON + timedelta(seconds=60),
        body=b"drop-me",
    )
    third = _add_segment(
        db_session,
        camera_id,
        NOON + timedelta(seconds=120),
        body=third_body,
    )
    work = tmp_path / "download-work"
    _pin_work_dir(monkeypatch, work)
    fetched: list[str] = []
    seen: list[list[UUID]] = []

    def concat(paths: list[Path], output: Path) -> None:
        seen.append([UUID(path.stem) for path in paths])
        output.write_bytes(b"".join(path.read_bytes() for path in paths))

    monkeypatch.setattr("app.services.recording_download.concat_mp4s", concat)
    _install_sources(
        monkeypatch,
        [first, middle, third],
        {first.id: "verified", middle.id: "tampered", third.id: "verified"},
        bodies={first.id: first_body, middle.id: b"drop-me", third.id: third_body},
        fetched=fetched,
    )

    response = _download(
        client,
        token,
        camera_id,
        NOON,
        third.ended_at,
    )
    report, video = _multipart(response)

    assert seen == [[first.id, third.id]]
    assert video == first_body + third_body
    assert b"drop-me" not in response.content
    assert middle.ipfs_cid not in fetched
    assert report["discontinuous"] is True
    assert "not one continuous recording" in str(report["detail"])
    statuses = {item["video_record_id"]: item["status"] for item in report["segments"]}
    assert statuses[str(first.id)] == "verified"
    assert statuses[str(middle.id)] == "tampered"
    assert statuses[str(third.id)] == "verified"
    excluded_ids = [
        item["video_record_id"] for item in report["excluded_intervals"]
    ]
    assert excluded_ids == [str(middle.id)]
    assert not work.exists()


def test_zero_verified_does_not_serve_a_file(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = _register_and_token(client, "dl-none@example.com")
    camera_id = _create_camera(client, token)
    record = _add_segment(db_session, camera_id, NOON)
    work = tmp_path / "download-work"
    _pin_work_dir(monkeypatch, work)
    fetched: list[str] = []
    _install_sources(
        monkeypatch,
        [record],
        {record.id: "tampered"},
        bodies={record.id: VIDEO},
        fetched=fetched,
    )

    ended = NOON + timedelta(minutes=5)
    response = _download(client, token, camera_id, NOON, ended)

    assert response.status_code == 409
    assert response.headers["content-type"].startswith("application/json")
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["overall"] == "tampered"
    assert body["discontinuous"] is False
    assert body["segments"][0]["status"] == "tampered"
    assert "nothing was downloaded" in body["detail"]
    assert body["missing_intervals"]
    assert body["missing_intervals"][0]["detail"]
    assert body["excluded_intervals"][0]["video_record_id"] == str(record.id)
    assert VIDEO not in response.content
    assert fetched == []
    assert str(work) not in response.text
    assert not work.exists()


def test_missing_interval_keeps_verified_portion(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = _register_and_token(client, "dl-gap@example.com")
    camera_id = _create_camera(client, token)
    record = _add_segment(db_session, camera_id, NOON)
    work = tmp_path / "download-work"
    _pin_work_dir(monkeypatch, work)
    _install_sources(
        monkeypatch,
        [record],
        {record.id: "verified"},
        bodies={record.id: VIDEO},
        fetched=[],
    )

    response = _download(
        client,
        token,
        camera_id,
        NOON,
        NOON + timedelta(minutes=5),
    )
    report, video = _multipart(response)

    assert video == VIDEO
    assert report["discontinuous"] is True
    assert report["overall"] == "missing"
    assert report["missing_intervals"]
    assert "12:01:00" in str(report["missing_intervals"][0]["started_at"])
    assert "not one continuous recording" in str(report["detail"])
    assert not work.exists()


def test_ipfs_failure_is_not_included(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = _register_and_token(client, "dl-ipfs@example.com")
    camera_id = _create_camera(client, token)
    good = _add_segment(db_session, camera_id, NOON, body=VIDEO)
    bad = _add_segment(
        db_session,
        camera_id,
        NOON + timedelta(seconds=60),
        body=b"missing-file",
    )
    work = tmp_path / "download-work"
    _pin_work_dir(monkeypatch, work)
    _install_sources(
        monkeypatch,
        [good, bad],
        {good.id: "verified", bad.id: "unavailable"},
        bodies={good.id: VIDEO, bad.id: b"missing-file"},
        fetched=[],
    )

    response = _download(client, token, camera_id, NOON, bad.ended_at)
    report, video = _multipart(response)

    assert video == VIDEO
    assert POISON not in response.content
    statuses = {item["video_record_id"]: item["status"] for item in report["segments"]}
    assert statuses[str(bad.id)] == "unavailable"
    assert report["discontinuous"] is True
    assert report["excluded_intervals"][0]["status"] == "unavailable"
    assert not work.exists()


def test_ipfs_failure_of_every_segment_serves_no_file(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = _register_and_token(client, "dl-ipfs-none@example.com")
    camera_id = _create_camera(client, token)
    record = _add_segment(db_session, camera_id, NOON)
    work = tmp_path / "download-work"
    _pin_work_dir(monkeypatch, work)
    _install_sources(
        monkeypatch,
        [record],
        {record.id: "unavailable"},
        bodies={record.id: VIDEO},
        fetched=[],
    )

    response = _download(client, token, camera_id, NOON, record.ended_at)
    assert response.status_code == 409
    body = response.json()
    assert body["overall"] == "unavailable"
    assert body["segments"][0]["status"] == "unavailable"
    assert POISON not in response.content
    assert VIDEO not in response.content
    assert not work.exists()


def test_hash_mismatch_is_tampered_and_not_served(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = _register_and_token(client, "dl-hash@example.com")
    camera_id = _create_camera(client, token)
    record = _add_segment(db_session, camera_id, NOON, body=VIDEO)
    work = tmp_path / "download-work"
    _pin_work_dir(monkeypatch, work)
    _install_sources(
        monkeypatch,
        [record],
        {record.id: "hash_mismatch"},
        bodies={record.id: VIDEO},
        fetched=[],
    )

    response = _download(client, token, camera_id, NOON, record.ended_at)
    assert response.status_code == 409
    body = response.json()
    assert body["overall"] == "tampered"
    assert body["segments"][0]["status"] == "tampered"
    assert "SHA-256" in body["segments"][0]["detail"]
    assert b"tampered-bytes" not in response.content
    assert not work.exists()


def test_chain_read_failure_serves_no_file(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = _register_and_token(client, "dl-chain@example.com")
    camera_id = _create_camera(client, token)
    record = _add_segment(db_session, camera_id, NOON)
    work = tmp_path / "download-work"
    _pin_work_dir(monkeypatch, work)
    fetched: list[str] = []
    _install_sources(
        monkeypatch,
        [record],
        {record.id: "failed"},
        bodies={record.id: VIDEO},
        fetched=fetched,
    )

    response = _download(client, token, camera_id, NOON, record.ended_at)
    assert response.status_code == 409
    body = response.json()
    assert body["overall"] == "failed"
    assert body["segments"][0]["status"] == "failed"
    assert fetched == []
    assert VIDEO not in response.content
    assert not work.exists()


def test_unaligned_segment_times_are_preserved(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = _register_and_token(client, "dl-offset@example.com")
    camera_id = _create_camera(client, token)
    started = NOON + timedelta(seconds=20)
    record = _add_segment(db_session, camera_id, started)
    work = tmp_path / "download-work"
    _pin_work_dir(monkeypatch, work)
    _install_sources(
        monkeypatch,
        [record],
        {record.id: "verified"},
        bodies={record.id: VIDEO},
        fetched=[],
    )

    response = _download(client, token, camera_id, started, record.ended_at)
    report, video = _multipart(response)
    assert video == VIDEO
    assert report["discontinuous"] is False
    assert "12:00:20" in str(report["segments"][0]["started_at"])
    assert "12:01:20" in str(report["segments"][0]["ended_at"])
    assert report["missing_intervals"] == []


def test_partial_window_uses_the_overlapping_segment(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = _register_and_token(client, "dl-window@example.com")
    camera_id = _create_camera(client, token)
    record = _add_segment(db_session, camera_id, NOON, seconds=120)
    work = tmp_path / "download-work"
    _pin_work_dir(monkeypatch, work)
    _install_sources(
        monkeypatch,
        [record],
        {record.id: "verified"},
        bodies={record.id: VIDEO},
        fetched=[],
    )

    response = _download(
        client,
        token,
        camera_id,
        NOON + timedelta(seconds=30),
        NOON + timedelta(seconds=90),
    )
    report, video = _multipart(response)
    assert video == VIDEO
    assert report["overall"] == "verified"
    assert report["missing_intervals"] == []
    assert "12:00:00" in str(report["segments"][0]["started_at"])
    assert "12:02:00" in str(report["segments"][0]["ended_at"])


def test_verification_failure_deletes_temp_dir(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = _register_and_token(client, "dl-boom@example.com")
    camera_id = _create_camera(client, token)
    work = tmp_path / "download-work"
    _pin_work_dir(monkeypatch, work)

    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("verification crashed")

    monkeypatch.setattr("app.routers.recordings.verify_recording_range", boom)
    with pytest.raises(RuntimeError, match="verification crashed"):
        _download(client, token, camera_id, NOON, NOON + timedelta(seconds=60))
    assert not work.exists()


def test_concat_failure_deletes_temp_dir(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = _register_and_token(client, "dl-concat@example.com")
    camera_id = _create_camera(client, token)
    first = _add_segment(db_session, camera_id, NOON, body=b"a")
    second = _add_segment(
        db_session,
        camera_id,
        NOON + timedelta(seconds=60),
        body=b"b",
    )
    work = tmp_path / "download-work"
    _pin_work_dir(monkeypatch, work)

    def concat(_paths: list[Path], _output: Path) -> None:
        raise RecordingDownloadError("Could not combine recordings into one file.")

    monkeypatch.setattr("app.services.recording_download.concat_mp4s", concat)
    _install_sources(
        monkeypatch,
        [first, second],
        {first.id: "verified", second.id: "verified"},
        bodies={first.id: b"a", second.id: b"b"},
        fetched=[],
    )

    response = _download(client, token, camera_id, NOON, second.ended_at)
    assert response.status_code == 502
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["detail"] == "Could not combine recordings into one file."
    assert not work.exists()


def test_download_response_deletes_temp_dir_when_send_fails(tmp_path: Path) -> None:
    work = tmp_path / "cancelled"
    work.mkdir()
    video = work / "clip.mp4"
    video.write_bytes(VIDEO)
    response = _VerifiedDownloadResponse(
        video_path=video,
        report_json={"overall": "verified", "detail": "ok"},
        filename="recording.mp4",
        cleanup_dir=str(work),
    )

    async def receive() -> dict[str, str]:
        return {"type": "http.request"}

    async def send(message: dict[str, object]) -> None:
        if message["type"] == "http.response.body":
            raise RuntimeError("client cancelled")

    with pytest.raises(RuntimeError, match="client cancelled"):
        anyio.run(response, {"type": "http"}, receive, send)

    assert not work.exists()
