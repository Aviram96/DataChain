"""Isolated tests for the automatic recording supervisor.

FFmpeg, PostgreSQL, IPFS, and the chain are not contacted. Lock contention uses
an in-memory lock or a fake connection. Camera rows live in a private SQLite
database.
"""

from __future__ import annotations

import importlib.util
import signal
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.camera import Camera
from app.models.user import User
from app.models.video_record import VideoRecord
from app.security.password import hash_password
from app.services.camera_ingest import camera_chunk_dir, write_run_pid
from app.services.ingest_supervisor import (
    IngestSupervisor,
    MemoryIngestLock,
    PostgresIngestLock,
    ProcessView,
    advisory_lock_keys,
    command_matches_camera,
    install_supervisor_signals,
    manual_ingest_available,
)

import app.models as _models  # noqa: F401


class FakeIngest:
    """Stand-in for CameraIngest. It never starts FFmpeg."""

    def __init__(self, config: object, **kwargs: object) -> None:
        self.config = config
        self.kwargs = kwargs
        self.stop_event = threading.Event()
        self.inactive_stop = False
        self.fail_immediately = False

    def stop(self, *, inactive: bool = False) -> None:
        if inactive:
            self.inactive_stop = True
        self.stop_event.set()

    def run_until_signal(self) -> int:
        if self.fail_immediately:
            return 1
        self.stop_event.wait()
        return 0


class Factory:
    def __init__(self, fail_remaining: int = 0) -> None:
        self.created: list[FakeIngest] = []
        self.fail_remaining = fail_remaining

    def __call__(self, config: object, **kwargs: object) -> FakeIngest:
        ingest = FakeIngest(config, **kwargs)
        if self.fail_remaining > 0:
            ingest.fail_immediately = True
            self.fail_remaining -= 1
        self.created.append(ingest)
        return ingest


class FakeInspector:
    def __init__(self) -> None:
        self.processes: dict[int, tuple[bool, str | None]] = {}
        self.terminated: list[int] = []
        self.killed: list[int] = []

    def inspect(self, pid: int) -> ProcessView:
        alive, command = self.processes.get(pid, (False, None))
        return ProcessView(alive=alive, command=command)

    def terminate(self, pid: int) -> None:
        self.terminated.append(pid)
        _alive, command = self.processes.get(pid, (False, None))
        self.processes[pid] = (False, command)

    def kill(self, pid: int) -> None:
        self.killed.append(pid)
        self.terminate(pid)


class FakeResult:
    def __init__(self, value: bool) -> None:
        self._value = value

    def scalar(self) -> bool:
        return self._value


class FakeConnection:
    def __init__(self, held: set[int]) -> None:
        self._held = held
        self._mine: list[int] = []
        self.closed = False
        self.detached = False
        self.commits = 0

    def execute(self, statement: object, params: dict[str, int]) -> FakeResult:
        sql = str(statement)
        key = params["k"]
        if "pg_try_advisory_lock" in sql:
            if key in self._held:
                return FakeResult(False)
            self._held.add(key)
            self._mine.append(key)
            return FakeResult(True)
        if "pg_advisory_unlock" in sql:
            self._held.discard(key)
            return FakeResult(True)
        raise AssertionError(sql)

    def commit(self) -> None:
        self.commits += 1

    def detach(self) -> None:
        self.detached = True

    def invalidate(self) -> None:
        for key in self._mine:
            self._held.discard(key)
        self._mine.clear()

    def close(self) -> None:
        self.closed = True


class FakeEngine:
    def __init__(self) -> None:
        self.held: set[int] = set()
        self.connections: list[FakeConnection] = []

    def connect(self) -> FakeConnection:
        connection = FakeConnection(self.held)
        self.connections.append(connection)
        return connection


def _fast_sleep(event: threading.Event, _seconds: float) -> bool:
    return event.is_set()


def _wait_until(predicate, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def _database() -> sessionmaker:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _add_camera(
    session_factory: sessionmaker,
    *,
    name: str,
    stream_url: str,
    deleted_at: datetime | None = None,
    record: bool = False,
) -> tuple[UUID, UUID | None]:
    db = session_factory()
    try:
        user = db.query(User).filter_by(email="owner@example.com").one_or_none()
        if user is None:
            user = User(
                email="owner@example.com",
                password_hash=hash_password("password12"),
            )
            db.add(user)
            db.flush()
        camera = Camera(
            user_id=user.id,
            name=name,
            stream_url=stream_url,
            deleted_at=deleted_at,
        )
        db.add(camera)
        db.flush()
        record_id = None
        if record:
            row = VideoRecord(
                camera_id=camera.id,
                started_at=datetime(2026, 11, 11, tzinfo=timezone.utc),
                ended_at=datetime(2026, 11, 11, 0, 1, tzinfo=timezone.utc),
                ipfs_cid="bafyexistingcid",
                segment_hash="ab" * 32,
                tx_hash="0x" + "12" * 32,
            )
            db.add(row)
            db.flush()
            record_id = row.id
        camera_id = camera.id
        db.commit()
        return camera_id, record_id
    finally:
        db.close()


def _supervisor(
    session_factory: sessionmaker,
    lock: MemoryIngestLock,
    factory: Factory,
    inspector: FakeInspector | None = None,
    tmp_path: Path | None = None,
) -> IngestSupervisor:
    return IngestSupervisor(
        session_factory=session_factory,
        lock=lock,
        temp_dir=tmp_path,
        ingest_factory=factory,
        process_inspector=inspector or FakeInspector(),
        sleeper=_fast_sleep,
        poll_interval_seconds=0.01,
        retry_initial_seconds=0.01,
        retry_max_seconds=0.05,
        orphan_wait_seconds=0.0,
        join_timeout_seconds=2.0,
    )


def test_new_active_camera_is_discovered(tmp_path: Path) -> None:
    session_factory = _database()
    lock = MemoryIngestLock()
    factory = Factory()
    supervisor = _supervisor(session_factory, lock, factory, tmp_path=tmp_path)
    supervisor.reconcile_once()
    assert factory.created == []

    camera_id, _record_id = _add_camera(
        session_factory,
        name="Gate",
        stream_url="rtsp://192.0.2.10/live",
    )
    supervisor.reconcile_once()
    assert _wait_until(lambda: len(factory.created) == 1)
    assert factory.created[0].config.camera_id == camera_id
    assert factory.created[0].kwargs["install_signal_handlers"] is False
    assert factory.created[0].kwargs["mark_offline_on_give_up"] is False
    assert lock.holds(camera_id)
    supervisor.shutdown()
    assert not lock.holds(camera_id)


def test_restored_camera_uses_the_original_id(tmp_path: Path) -> None:
    session_factory = _database()
    camera_id, record_id = _add_camera(
        session_factory,
        name="Gate",
        stream_url="rtsp://192.0.2.10/live",
        deleted_at=datetime(2026, 11, 17, tzinfo=timezone.utc),
        record=True,
    )
    lock = MemoryIngestLock()
    factory = Factory()
    supervisor = _supervisor(session_factory, lock, factory, tmp_path=tmp_path)
    supervisor.reconcile_once()
    assert factory.created == []

    db = session_factory()
    try:
        camera = db.get(Camera, camera_id)
        assert camera is not None
        camera.deleted_at = None
        db.commit()
    finally:
        db.close()

    supervisor.reconcile_once()
    assert _wait_until(lambda: len(factory.created) == 1)
    assert factory.created[0].config.camera_id == camera_id
    supervisor.shutdown()

    db = session_factory()
    try:
        row = db.get(VideoRecord, record_id)
        assert row is not None
        assert row.camera_id == camera_id
        assert row.ipfs_cid == "bafyexistingcid"
        assert row.segment_hash == "ab" * 32
        assert row.tx_hash == "0x" + "12" * 32
    finally:
        db.close()


def test_archive_stops_recording_and_does_not_restart(tmp_path: Path) -> None:
    session_factory = _database()
    camera_id, record_id = _add_camera(
        session_factory,
        name="Gate",
        stream_url="rtsp://192.0.2.10/live",
        record=True,
    )
    before = _record_snapshot(session_factory, record_id)
    lock = MemoryIngestLock()
    factory = Factory()
    supervisor = _supervisor(session_factory, lock, factory, tmp_path=tmp_path)
    supervisor.reconcile_once()
    assert _wait_until(lambda: len(factory.created) == 1)

    db = session_factory()
    try:
        camera = db.get(Camera, camera_id)
        assert camera is not None
        camera.deleted_at = datetime(2026, 11, 18, tzinfo=timezone.utc)
        db.commit()
    finally:
        db.close()

    supervisor.reconcile_once()
    assert _wait_until(lambda: factory.created[0].inactive_stop)
    run = supervisor._runs.get(camera_id)
    if run is not None:
        run.thread.join(timeout=2)
    supervisor.reconcile_once()
    assert len(factory.created) == 1
    assert factory.created[0].inactive_stop is True
    assert not lock.holds(camera_id)
    assert _record_snapshot(session_factory, record_id) == before
    supervisor.shutdown()


def test_rtsp_failure_retries_and_recovers(tmp_path: Path) -> None:
    session_factory = _database()
    camera_id, _record_id = _add_camera(
        session_factory,
        name="Gate",
        stream_url="rtsp://192.0.2.10/live",
    )
    lock = MemoryIngestLock()
    factory = Factory(fail_remaining=1)
    supervisor = _supervisor(session_factory, lock, factory, tmp_path=tmp_path)
    supervisor.reconcile_once()
    assert _wait_until(lambda: len(factory.created) == 2)
    assert factory.created[0].fail_immediately is True
    assert factory.created[1].fail_immediately is False
    assert factory.created[1].config.camera_id == camera_id
    assert not factory.created[1].stop_event.is_set()
    assert lock.holds(camera_id)
    assert len(supervisor._runs) == 1
    supervisor.shutdown()
    assert not lock.holds(camera_id)


def test_several_cameras_record_together(tmp_path: Path) -> None:
    session_factory = _database()
    first, _record = _add_camera(
        session_factory,
        name="Gate",
        stream_url="rtsp://192.0.2.10/a",
    )
    second, _record = _add_camera(
        session_factory,
        name="Yard",
        stream_url="rtsp://192.0.2.11/b",
    )
    lock = MemoryIngestLock()
    factory = Factory()
    supervisor = _supervisor(session_factory, lock, factory, tmp_path=tmp_path)
    supervisor.reconcile_once()
    assert _wait_until(lambda: len(factory.created) == 2)
    started = {item.config.camera_id for item in factory.created}
    assert started == {first, second}
    assert lock.holds(first)
    assert lock.holds(second)
    supervisor.shutdown()
    assert not lock.holds(first)
    assert not lock.holds(second)


def test_second_supervisor_and_manual_cli_cannot_take_the_lock(
    tmp_path: Path,
) -> None:
    session_factory = _database()
    camera_id, _record = _add_camera(
        session_factory,
        name="Gate",
        stream_url="rtsp://192.0.2.10/live",
    )
    lock = MemoryIngestLock()
    first_factory = Factory()
    second_factory = Factory()
    first = _supervisor(session_factory, lock, first_factory, tmp_path=tmp_path)
    second = _supervisor(session_factory, lock, second_factory, tmp_path=tmp_path)
    first.reconcile_once()
    assert _wait_until(lambda: len(first_factory.created) == 1)
    second.reconcile_once()
    assert second_factory.created == []
    assert manual_ingest_available(lock, camera_id) is False
    first.shutdown()
    assert manual_ingest_available(lock, camera_id) is True
    lock.release(camera_id)


def test_restart_stops_verified_orphan_then_starts_one(tmp_path: Path) -> None:
    session_factory = _database()
    camera_id, _record = _add_camera(
        session_factory,
        name="Gate",
        stream_url="rtsp://192.0.2.10/live",
    )
    folder = camera_chunk_dir(camera_id, tmp_path)
    folder.mkdir(parents=True)
    csv_path = folder / "segments_old.csv"
    csv_path.write_text("", encoding="utf-8")
    write_run_pid(csv_path, 4242)
    inspector = FakeInspector()
    inspector.processes[4242] = (
        True,
        f"ffmpeg -i rtsp://192.0.2.10/live {folder / (str(camera_id) + '_x.mp4')}",
    )
    lock = MemoryIngestLock()
    factory = Factory()
    supervisor = _supervisor(
        session_factory,
        lock,
        factory,
        inspector=inspector,
        tmp_path=tmp_path,
    )
    supervisor.reconcile_once()
    assert _wait_until(lambda: len(factory.created) == 1)
    assert inspector.terminated == [4242]
    assert inspector.killed == []
    assert len(factory.created) == 1
    supervisor.shutdown()


def test_unverified_live_pid_is_not_killed_or_duplicated(tmp_path: Path) -> None:
    session_factory = _database()
    camera_id, _record = _add_camera(
        session_factory,
        name="Gate",
        stream_url="rtsp://192.0.2.10/live",
    )
    folder = camera_chunk_dir(camera_id, tmp_path)
    folder.mkdir(parents=True)
    csv_path = folder / "segments_old.csv"
    csv_path.write_text("", encoding="utf-8")
    write_run_pid(csv_path, 77)
    inspector = FakeInspector()
    inspector.processes[77] = (True, None)
    lock = MemoryIngestLock()
    factory = Factory()
    supervisor = _supervisor(
        session_factory,
        lock,
        factory,
        inspector=inspector,
        tmp_path=tmp_path,
    )
    supervisor.reconcile_once()
    assert factory.created == []
    assert inspector.terminated == []
    assert lock.holds(camera_id)

    inspector.processes[77] = (False, None)
    supervisor.reconcile_once()
    assert _wait_until(lambda: len(factory.created) == 1)
    assert inspector.terminated == []
    supervisor.shutdown()


def test_reused_pid_of_another_program_is_not_killed(tmp_path: Path) -> None:
    session_factory = _database()
    camera_id, _record = _add_camera(
        session_factory,
        name="Gate",
        stream_url="rtsp://192.0.2.10/live",
    )
    folder = camera_chunk_dir(camera_id, tmp_path)
    folder.mkdir(parents=True)
    csv_path = folder / "segments_old.csv"
    csv_path.write_text("", encoding="utf-8")
    write_run_pid(csv_path, 88)
    inspector = FakeInspector()
    inspector.processes[88] = (True, "python other_service.py")
    lock = MemoryIngestLock()
    factory = Factory()
    supervisor = _supervisor(
        session_factory,
        lock,
        factory,
        inspector=inspector,
        tmp_path=tmp_path,
    )
    supervisor.reconcile_once()
    assert _wait_until(lambda: len(factory.created) == 1)
    assert inspector.terminated == []
    supervisor.shutdown()


def test_stream_url_change_restarts_only_that_camera(tmp_path: Path) -> None:
    session_factory = _database()
    changed, _record = _add_camera(
        session_factory,
        name="Gate",
        stream_url="rtsp://192.0.2.10/old",
    )
    other, _record = _add_camera(
        session_factory,
        name="Yard",
        stream_url="rtsp://192.0.2.11/steady",
    )
    lock = MemoryIngestLock()
    factory = Factory()
    supervisor = _supervisor(session_factory, lock, factory, tmp_path=tmp_path)
    supervisor.reconcile_once()
    assert _wait_until(lambda: len(factory.created) == 2)

    db = session_factory()
    try:
        camera = db.get(Camera, changed)
        assert camera is not None
        camera.stream_url = "rtsp://192.0.2.10/new"
        db.commit()
    finally:
        db.close()

    supervisor.reconcile_once()
    assert _wait_until(lambda: len(factory.created) == 3)
    restarted = [item for item in factory.created if item.config.camera_id == changed]
    untouched = [item for item in factory.created if item.config.camera_id == other]
    assert len(restarted) == 2
    assert restarted[0].inactive_stop is False
    assert restarted[1].config.stream_url == "rtsp://192.0.2.10/new"
    assert len(untouched) == 1
    assert not untouched[0].stop_event.is_set()
    assert lock.holds(changed)
    assert lock.holds(other)
    supervisor.shutdown()


def test_database_failure_does_not_start_a_second_worker(tmp_path: Path) -> None:
    session_factory = _database()
    camera_id, _record = _add_camera(
        session_factory,
        name="Gate",
        stream_url="rtsp://192.0.2.10/live",
    )
    calls = {"n": 0}

    def flaky() -> object:
        calls["n"] += 1
        # The list and the post-lock active check both need a session.
        # Later reads fail, including the worker's own retry lookup.
        if calls["n"] > 2:
            raise RuntimeError("database unavailable")
        return session_factory()

    lock = MemoryIngestLock()
    factory = Factory(fail_remaining=1)
    supervisor = _supervisor(session_factory, lock, factory, tmp_path=tmp_path)
    supervisor._session_factory = flaky  # type: ignore[assignment]
    supervisor.reconcile_once()
    assert _wait_until(lambda: len(factory.created) == 1)
    time.sleep(0.05)
    supervisor.reconcile_once()
    assert len(factory.created) == 1
    assert lock.holds(camera_id)
    assert len(supervisor._runs) == 1
    supervisor.shutdown()


def test_run_starts_and_shutdown_releases_locks(tmp_path: Path) -> None:
    session_factory = _database()
    camera_id, _record = _add_camera(
        session_factory,
        name="Gate",
        stream_url="rtsp://192.0.2.10/live",
    )
    lock = MemoryIngestLock()
    factory = Factory()
    supervisor = _supervisor(session_factory, lock, factory, tmp_path=tmp_path)
    thread = threading.Thread(target=supervisor.run)
    thread.start()
    assert _wait_until(lambda: len(factory.created) == 1)
    supervisor.request_shutdown()
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert not lock.holds(camera_id)


def test_shutdown_before_run_starts_nothing(tmp_path: Path) -> None:
    session_factory = _database()
    _add_camera(session_factory, name="Gate", stream_url="rtsp://192.0.2.10/live")
    lock = MemoryIngestLock()
    factory = Factory()
    supervisor = _supervisor(session_factory, lock, factory, tmp_path=tmp_path)
    supervisor.request_shutdown()
    assert supervisor.run() == 0
    assert factory.created == []
    assert lock._held == set()


def test_signal_handler_only_requests_shutdown(tmp_path: Path) -> None:
    session_factory = _database()
    lock = MemoryIngestLock()
    factory = Factory()
    supervisor = _supervisor(session_factory, lock, factory, tmp_path=tmp_path)
    previous_int = signal.getsignal(signal.SIGINT)
    previous_term = signal.getsignal(signal.SIGTERM)
    try:
        install_supervisor_signals(supervisor)
        handler = signal.getsignal(signal.SIGTERM)
        assert callable(handler)
        handler(signal.SIGTERM, None)
        assert supervisor._shutdown.is_set()
        assert factory.created == []
    finally:
        signal.signal(signal.SIGINT, previous_int)
        signal.signal(signal.SIGTERM, previous_term)


def test_postgres_lock_is_held_until_release_and_blocks_a_second_owner() -> None:
    engine = FakeEngine()
    first = PostgresIngestLock(engine)  # type: ignore[arg-type]
    second = PostgresIngestLock(engine)  # type: ignore[arg-type]
    camera_id = uuid4()
    assert first.try_acquire(camera_id) is True
    connection = engine.connections[0]
    assert connection.detached is True
    assert connection.closed is False
    assert second.try_acquire(camera_id) is False
    first.release(camera_id)
    assert connection.closed is True
    assert engine.held == set()
    assert second.try_acquire(camera_id) is True
    second.release(camera_id)


def test_advisory_lock_keys_cover_the_uuid() -> None:
    camera_id = uuid4()
    other = uuid4()
    assert advisory_lock_keys(camera_id) == advisory_lock_keys(camera_id)
    assert advisory_lock_keys(camera_id) != advisory_lock_keys(other)
    for key in advisory_lock_keys(camera_id):
        assert -(2**63) <= key < 2**63


def test_command_match_requires_ffmpeg_and_this_camera(tmp_path: Path) -> None:
    camera_id = uuid4()
    folder = tmp_path / str(camera_id)
    assert command_matches_camera(
        f"ffmpeg -i rtsp://192.0.2.10/live {folder / 'out.mp4'}",
        camera_id=camera_id,
        temp_dir=folder,
        ffmpeg_executable="ffmpeg",
    )
    assert not command_matches_camera(
        "python other.py",
        camera_id=camera_id,
        temp_dir=folder,
        ffmpeg_executable="ffmpeg",
    )
    assert not command_matches_camera(
        "ffmpeg -i rtsp://192.0.2.10/other",
        camera_id=camera_id,
        temp_dir=folder,
        ffmpeg_executable="ffmpeg",
    )


def test_deleted_camera_is_not_started_after_the_ingest_lock(
    tmp_path: Path,
) -> None:
    """A stale active list must not start ingest once the row is gone.

    The delete runs after the lock is held and before a worker starts. That
    is the window where checking the camera only before the lock would race.
    """
    session_factory = _database()
    camera_id, _record_id = _add_camera(
        session_factory,
        name="Gate",
        stream_url="rtsp://192.0.2.10/live",
    )
    lock = MemoryIngestLock()
    factory = Factory()
    supervisor = _supervisor(session_factory, lock, factory, tmp_path=tmp_path)
    original_hold = supervisor._hold_lock

    def hold_then_delete(held_id: UUID) -> bool:
        acquired = original_hold(held_id)
        if not acquired:
            return False
        db = session_factory()
        try:
            db.query(Camera).filter(Camera.id == held_id).delete()
            db.commit()
        finally:
            db.close()
        return True

    supervisor._hold_lock = hold_then_delete  # type: ignore[method-assign]
    supervisor.reconcile_once()
    assert factory.created == []
    assert not lock.holds(camera_id)


def test_supervise_cli_mode_parses() -> None:
    path = Path(__file__).resolve().parents[1] / "scripts" / "ingest_camera.py"
    spec = importlib.util.spec_from_file_location("ingest_camera_cli", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    args = module._parse_args(["--supervise"])
    assert args.supervise is True
    assert args.all is False
    assert args.camera_id is None


def _record_snapshot(
    session_factory: sessionmaker,
    record_id: UUID | None,
) -> tuple[object, ...]:
    db = session_factory()
    try:
        row = db.get(VideoRecord, record_id)
        assert row is not None
        return (
            row.id,
            row.camera_id,
            row.started_at,
            row.ended_at,
            row.ipfs_cid,
            row.segment_hash,
            row.tx_hash,
        )
    finally:
        db.close()
