"""Tests for camera stream ingest and chunking (Slice C / CP-C.P2–P4)."""

from __future__ import annotations

import io
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

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
    read_run_pid,
    recover_orphan_segment_runs,
    resolve_ingest_max_restarts,
    write_run_pid,
)
from app.services.camera_stream import CameraNotFoundForStream, list_active_cameras
from app.services.segment_identity import camera_segment_pattern
from app.services.segment_timeline import is_segment_run_closed

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


def test_build_ffmpeg_receive_command_loop_is_realtime(tmp_path: Path) -> None:
    config = CameraIngestConfig(
        camera_id=uuid4(),
        stream_url="http://127.0.0.1:8080/sample2.mp4",
        temp_dir=tmp_path,
        loop_source=True,
    )
    cmd = build_ffmpeg_receive_command(config)
    assert cmd[cmd.index("-re") + 1] == "-stream_loop"
    assert cmd[cmd.index("-stream_loop") + 1] == "-1"
    assert cmd[cmd.index("-i") + 1] == "http://127.0.0.1:8080/sample2.mp4"


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
    markers = list(camera_chunk_dir(live.id, tmp_path).glob("segments_*.csv.closed"))
    assert len(markers) == 1


def test_ingest_closes_each_restarted_run(
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _user, live, _http = _user_with_cameras(db_session)
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
        assert ingest.run_until_signal() == 1
    markers = list(camera_chunk_dir(live.id, tmp_path).glob("segments_*.csv.closed"))
    assert len(markers) == 2


def test_recovery_closes_only_a_recorded_dead_pid(tmp_path: Path) -> None:
    gone = tmp_path / "segments_gone.csv"
    live = tmp_path / "segments_live.csv"
    unknown = tmp_path / "segments_unknown.csv"
    untracked = tmp_path / "segments_untracked.csv"
    already = tmp_path / "segments_done.csv"
    for path in (gone, live, unknown, untracked, already):
        path.write_text("a.mp4,0,1\n")
    write_run_pid(gone, 101)
    write_run_pid(live, 202)
    write_run_pid(unknown, 303)
    (tmp_path / "segments_done.csv.closed").write_text("")
    (tmp_path / "segments_done.csv.pid").write_text("404\n")

    def alive(pid: int) -> bool | None:
        if pid == 101:
            return False
        if pid == 202:
            return True
        return None

    closed = recover_orphan_segment_runs(tmp_path, pid_is_alive=alive)

    assert closed == [gone]
    assert is_segment_run_closed(gone)
    assert not is_segment_run_closed(live)
    assert not is_segment_run_closed(unknown)
    assert not is_segment_run_closed(untracked)
    assert is_segment_run_closed(already)


def test_recovery_does_not_close_when_the_pid_returns(tmp_path: Path) -> None:
    csv_path = tmp_path / "segments_race.csv"
    csv_path.write_text("a.mp4,0,1\n")
    write_run_pid(csv_path, 505)
    answers = iter((False, True))

    def alive(_pid: int) -> bool | None:
        return next(answers)

    assert recover_orphan_segment_runs(tmp_path, pid_is_alive=alive) == []
    assert not is_segment_run_closed(csv_path)


def test_corrupt_pid_file_is_not_treated_as_a_finished_run(tmp_path: Path) -> None:
    csv_path = tmp_path / "segments_bad.csv"
    csv_path.write_text("a.mp4,0,1\n")
    (tmp_path / "segments_bad.csv.pid").write_text("not-a-pid\n")

    assert read_run_pid(csv_path) is None
    assert recover_orphan_segment_runs(tmp_path, pid_is_alive=lambda _pid: False) == []
    assert not is_segment_run_closed(csv_path)


def test_ingest_records_ffmpeg_pid_before_the_run_closes(
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _user, live, _http = _user_with_cameras(db_session)
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
    proc = MagicMock(
        wait=MagicMock(return_value=0),
        stderr=None,
        poll=MagicMock(return_value=0),
        pid=5151,
    )
    ingest = CameraIngest(config, session_factory=SessionLocal)
    with patch(
        "app.services.ffmpeg_supervisor.subprocess.Popen",
        return_value=proc,
    ):
        assert ingest.run_until_signal() == 0
    staging = camera_chunk_dir(live.id, tmp_path)
    pid_files = list(staging.glob("segments_*.csv.pid"))
    markers = list(staging.glob("segments_*.csv.closed"))
    assert len(pid_files) == 1
    assert len(markers) == 1
    assert pid_files[0].read_text(encoding="utf-8").strip() == "5151"
    assert pid_files[0].name.replace(".pid", ".closed") == markers[0].name


class _StopStream(io.BytesIO):
    def __init__(self, released: threading.Event) -> None:
        super().__init__()
        self._released = released

    def write(self, data: bytes) -> int:  # type: ignore[override]
        self._released.set()
        return super().write(data)

    def flush(self) -> None:
        return None


class _HoldingFFmpeg:
    """FFmpeg stand-in that runs until ingest asks it to stop."""

    def __init__(self) -> None:
        self.released = threading.Event()
        self.stdin = _StopStream(self.released)
        self.stderr = None
        self.pid = 4242
        self.returncode: int | None = None
        self._lock = threading.Lock()

    def poll(self) -> int | None:
        with self._lock:
            return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        if not self.released.wait(timeout):
            raise subprocess.TimeoutExpired("ffmpeg", timeout or 0)
        with self._lock:
            if self.returncode is None:
                self.returncode = 0
            return self.returncode

    def terminate(self) -> None:
        with self._lock:
            self.returncode = -15
        self.released.set()

    def kill(self) -> None:
        with self._lock:
            self.returncode = -9
        self.released.set()


def _running_ingest(
    tmp_path: Path,
) -> tuple[sessionmaker, UUID, CameraIngest]:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'ingest.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = session_factory()
    user = User(email="watch@example.com", password_hash=hash_password("password12"))
    db.add(user)
    db.flush()
    camera = Camera(
        user_id=user.id,
        name="Gate",
        stream_url="rtsp://192.0.2.50/live",
    )
    db.add(camera)
    db.commit()
    camera_id = camera.id
    stream_url = camera.stream_url
    db.close()
    config = CameraIngestConfig(
        camera_id=camera_id,
        stream_url=stream_url,
        temp_dir=tmp_path / "chunks",
    )
    return (
        session_factory,
        camera_id,
        CameraIngest(config, session_factory=session_factory),
    )


def _run_until_stopped(
    ingest: CameraIngest,
    monkeypatch: pytest.MonkeyPatch,
) -> int:
    monkeypatch.setattr(
        "app.services.camera_ingest.ACTIVE_CAMERA_CHECK_SECONDS",
        0.05,
    )
    result: dict[str, object] = {}

    def run() -> None:
        try:
            with patch(
                "app.services.ffmpeg_supervisor.subprocess.Popen",
                return_value=_HoldingFFmpeg(),
            ):
                result["code"] = ingest.run_until_signal()
        except Exception as exc:  # pragma: no cover - failure signal for the join
            result["error"] = exc

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(5)
    assert not worker.is_alive()
    assert "error" not in result
    assert result["code"] == 0
    return 0


def test_inactive_stop_before_ffmpeg_does_not_start_it(
    tmp_path: Path,
) -> None:
    session_factory, camera_id, ingest = _running_ingest(tmp_path)
    ingest.stop(inactive=True)
    with patch("app.services.ffmpeg_supervisor.subprocess.Popen") as popen:
        assert ingest.run_until_signal() == 0
    popen.assert_not_called()
    db = session_factory()
    try:
        row = db.get(Camera, camera_id)
        assert row is not None
        assert row.ingest_offline_at is None
        assert ingest.inactive_stop is True
    finally:
        db.close()


def test_external_inactive_stop_skips_final_flush(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.chunk_processing_worker import ChunkProcessingWorker

    _session_factory, _camera_id, ingest = _running_ingest(tmp_path)
    seen: dict[str, bool] = {}
    original = ChunkProcessingWorker.stop

    def spy(self: ChunkProcessingWorker, *, flush: bool = True) -> None:
        seen["flush"] = flush
        original(self, flush=flush)

    monkeypatch.setattr(ChunkProcessingWorker, "stop", spy)

    def stop_soon() -> None:
        time.sleep(0.2)
        ingest.stop(inactive=True)

    threading.Thread(target=stop_soon, daemon=True).start()
    _run_until_stopped(ingest, monkeypatch)
    assert seen["flush"] is False
    assert ingest.inactive_stop is True


def test_retryable_give_up_does_not_mark_offline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory, camera_id, _existing = _running_ingest(tmp_path)
    seen: dict[str, object] = {}

    class FakeSupervisor:
        def __init__(self, config: object) -> None:
            seen["handlers"] = getattr(config, "install_signal_handlers", None)
            self.gave_up_after_restarts = True
            self.restart_count = 0

        def run_until_signal(self) -> int:
            return 1

        def stop(self) -> None:
            return None

    class FakeWorker:
        def __init__(self, config: object) -> None:
            return None

        def start(self) -> None:
            return None

        def stop(self, *, flush: bool = True) -> None:
            seen["flush"] = flush

    monkeypatch.setattr("app.services.camera_ingest.FFmpegSupervisor", FakeSupervisor)
    monkeypatch.setattr("app.services.camera_ingest.ChunkProcessingWorker", FakeWorker)
    ingest = CameraIngest(
        CameraIngestConfig(
            camera_id=camera_id,
            stream_url="rtsp://192.0.2.50/live",
            temp_dir=tmp_path / "chunks",
        ),
        session_factory=session_factory,
        install_signal_handlers=False,
        mark_offline_on_give_up=False,
        max_restarts=0,
    )
    assert ingest.run_until_signal() == 1
    db = session_factory()
    try:
        row = db.get(Camera, camera_id)
        assert row is not None
        assert row.ingest_offline_at is None
        assert seen["handlers"] is False
        assert seen["flush"] is True
    finally:
        db.close()


def test_archive_stops_running_ingest_without_marking_offline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory, camera_id, ingest = _running_ingest(tmp_path)

    def archive_soon() -> None:
        time.sleep(0.15)
        db = session_factory()
        row = db.get(Camera, camera_id)
        assert row is not None
        row.deleted_at = datetime.now(timezone.utc)
        db.commit()
        db.close()

    threading.Thread(target=archive_soon, daemon=True).start()
    _run_until_stopped(ingest, monkeypatch)

    db = session_factory()
    try:
        row = db.get(Camera, camera_id)
        assert row is not None
        assert row.deleted_at is not None
        assert row.ingest_offline_at is None
        assert ingest._inactive_stop is True
        assert ingest._supervisor is not None
        assert ingest._supervisor.gave_up_after_restarts is False
    finally:
        db.close()


def test_database_error_stops_ingest_without_marking_offline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import camera_ingest as ingest_module

    session_factory, camera_id, ingest = _running_ingest(tmp_path)
    original = ingest_module.get_active_camera
    armed = {"on": False}

    def flaky(db: Session, checked_id: UUID) -> Camera:
        if armed["on"]:
            raise RuntimeError("database unavailable")
        return original(db, checked_id)

    monkeypatch.setattr(ingest_module, "get_active_camera", flaky)

    def arm() -> None:
        time.sleep(0.12)
        armed["on"] = True

    threading.Thread(target=arm, daemon=True).start()
    _run_until_stopped(ingest, monkeypatch)

    db = session_factory()
    try:
        row = db.get(Camera, camera_id)
        assert row is not None
        assert row.deleted_at is None
        assert row.ingest_offline_at is None
        assert ingest._inactive_stop is True
        assert ingest._supervisor is not None
        assert ingest._supervisor.gave_up_after_restarts is False
    finally:
        db.close()
