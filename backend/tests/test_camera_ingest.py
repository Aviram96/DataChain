"""Tests for camera stream ingest and chunking (Slice C / CP-C.P2–P4)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.camera import Camera
from app.models.user import User
from app.security.password import hash_password
from app.services.camera_ingest import (
    CameraIngest,
    CameraIngestConfig,
    build_ffmpeg_receive_command,
    camera_chunk_dir,
    camera_offline_reason,
    chunker_config_for_ingest,
    clear_ingest_offline,
    effective_camera_status,
    ingest_config_for_camera,
    ingest_configs_for_all_active,
    mark_ingest_offline,
    resolve_ingest_max_restarts,
)
from app.services.camera_stream import CameraNotFoundForStream, list_active_cameras
from app.services.segment_identity import camera_segment_pattern

import app.models as _models  # noqa: F401


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


def _user_with_cameras(db_session: Session) -> tuple[User, Camera, Camera]:
    user = User(email="ingest@example.com", password_hash=hash_password("password12"))
    db_session.add(user)
    db_session.flush()
    live = Camera(
        user_id=user.id,
        name="Front",
        stream_url="rtsp://192.0.2.50/live",
    )
    http = Camera(
        user_id=user.id,
        name="Lobby",
        stream_url="http://192.0.2.51/stream",
    )
    db_session.add_all([live, http])
    db_session.commit()
    return user, live, http


def test_build_ffmpeg_receive_command_rtsp_chunks_to_mp4(tmp_path: Path) -> None:
    camera_id = uuid4()
    config = CameraIngestConfig(
        camera_id=camera_id,
        stream_url="rtsp://192.0.2.50/live",
        temp_dir=tmp_path,
    )
    cmd = build_ffmpeg_receive_command(config)
    assert cmd[0] == "ffmpeg"
    assert "-rtsp_transport" in cmd
    assert cmd[cmd.index("-rtsp_transport") + 1] == "tcp"
    assert cmd[cmd.index("-i") + 1] == "rtsp://192.0.2.50/live"
    assert cmd[cmd.index("-f") + 1] == "segment"
    assert cmd[cmd.index("-segment_time") + 1] == "60"
    assert "-stream_loop" not in cmd
    out = str(camera_chunk_dir(camera_id, tmp_path) / f"{camera_id}_%Y%m%dT%H%M%SZ.mp4")
    assert out in cmd
    assert "-strftime" in cmd
    assert cmd[cmd.index("-strftime") + 1] == "1"


def test_build_ffmpeg_receive_command_http_skips_rtsp_flag(tmp_path: Path) -> None:
    config = CameraIngestConfig(
        camera_id=uuid4(),
        stream_url="https://192.0.2.51/stream",
        temp_dir=tmp_path,
    )
    cmd = build_ffmpeg_receive_command(config)
    assert "-rtsp_transport" not in cmd
    assert cmd[cmd.index("-i") + 1] == "https://192.0.2.51/stream"


def test_ingest_config_for_camera_attaches_url(db_session: Session) -> None:
    _user, live, _http = _user_with_cameras(db_session)
    config = ingest_config_for_camera(db_session, live.id)
    assert config.camera_id == live.id
    assert config.stream_url == "rtsp://192.0.2.50/live"
    assert config.segment_duration_seconds == 60


def test_ingest_config_rejects_unknown_camera(db_session: Session) -> None:
    with pytest.raises(CameraNotFoundForStream):
        ingest_config_for_camera(db_session, uuid4())


def test_ingest_configs_for_all_active_skips_deleted(db_session: Session) -> None:
    _user, live, http = _user_with_cameras(db_session)
    http.deleted_at = datetime.now(timezone.utc)
    db_session.commit()

    active = list_active_cameras(db_session)
    assert [camera.id for camera in active] == [live.id]

    configs = ingest_configs_for_all_active(db_session)
    assert len(configs) == 1
    assert configs[0].camera_id == live.id
    chunk = chunker_config_for_ingest(configs[0])
    assert chunk.temp_dir == camera_chunk_dir(live.id)
    assert chunk.input_uri == live.stream_url
    assert chunk.segment_duration_seconds == 60
    assert chunk.segment_pattern == camera_segment_pattern(live.id)
    assert chunk.strftime_output is True


def test_resolve_ingest_max_restarts_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CCTV_FFMPEG_MAX_RESTARTS", raising=False)
    assert resolve_ingest_max_restarts() == 10


def test_resolve_ingest_max_restarts_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CCTV_FFMPEG_MAX_RESTARTS", "3")
    assert resolve_ingest_max_restarts() == 3


def test_effective_camera_status_uses_ingest_offline(db_session: Session) -> None:
    _user, live, _http = _user_with_cameras(db_session)
    assert effective_camera_status(live, "online") == "online"
    live.ingest_offline_at = datetime.now(timezone.utc)
    assert effective_camera_status(live, "online") == "offline"


def test_camera_offline_reason_distinguishes_ingest_vs_probe(
    db_session: Session,
) -> None:
    _user, live, _http = _user_with_cameras(db_session)
    assert camera_offline_reason(live, "online") is None
    assert camera_offline_reason(live, "offline") == "unreachable"
    live.ingest_offline_at = datetime.now(timezone.utc)
    assert camera_offline_reason(live, "online") == "ingest_failed"
    assert camera_offline_reason(live, "offline") == "ingest_failed"


def test_mark_and_clear_ingest_offline(db_session: Session) -> None:
    _user, live, _http = _user_with_cameras(db_session)
    mark_ingest_offline(db_session, live.id)
    db_session.refresh(live)
    assert live.ingest_offline_at is not None
    clear_ingest_offline(db_session, live.id)
    db_session.refresh(live)
    assert live.ingest_offline_at is None


def test_ingest_clears_offline_on_start_and_marks_after_restart_cap(
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _user, live, _http = _user_with_cameras(db_session)
    live.ingest_offline_at = datetime.now(timezone.utc)
    db_session.commit()
    monkeypatch.setenv("CCTV_FFMPEG_MAX_RESTARTS", "1")
    monkeypatch.setenv("CCTV_FFMPEG_RESTART_DELAY_SECONDS", "0")
    SessionLocal = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=db_session.get_bind(),
    )
    config = CameraIngestConfig(
        camera_id=live.id,
        stream_url=live.stream_url,
        temp_dir=tmp_path,
    )
    crashing = MagicMock(
        wait=MagicMock(return_value=1),
        stderr=None,
        poll=MagicMock(return_value=1),
    )
    ingest = CameraIngest(config, session_factory=SessionLocal)
    with patch(
        "app.services.ffmpeg_supervisor.subprocess.Popen",
        return_value=crashing,
    ):
        code = ingest.run_until_signal()
    assert code == 1
    assert ingest._supervisor is not None
    assert ingest._supervisor.gave_up_after_restarts is True
    db_session.expire_all()
    db_session.refresh(live)
    assert live.ingest_offline_at is not None


def test_ingest_clears_offline_when_ffmpeg_exits_cleanly(
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _user, live, _http = _user_with_cameras(db_session)
    live.ingest_offline_at = datetime.now(timezone.utc)
    db_session.commit()
    monkeypatch.setenv("CCTV_FFMPEG_RESTART_DELAY_SECONDS", "0")
    SessionLocal = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=db_session.get_bind(),
    )
    config = CameraIngestConfig(
        camera_id=live.id,
        stream_url=live.stream_url,
        temp_dir=tmp_path,
    )
    clean = MagicMock(
        wait=MagicMock(return_value=0),
        stderr=None,
        poll=MagicMock(return_value=0),
    )
    ingest = CameraIngest(config, session_factory=SessionLocal)
    with patch(
        "app.services.ffmpeg_supervisor.subprocess.Popen",
        return_value=clean,
    ):
        code = ingest.run_until_signal()
    assert code == 0
    assert ingest._supervisor is not None
    assert ingest._supervisor.gave_up_after_restarts is False
    db_session.expire_all()
    db_session.refresh(live)
    assert live.ingest_offline_at is None
