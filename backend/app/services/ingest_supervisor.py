"""Watch active cameras and run one ingest worker for each.

The API does not start this loop. Operators run ``scripts/ingest_camera.py
--supervise``. Create, restore, and archive stay database writes. This process
notices those rows and starts or stops ``CameraIngest``.

One PostgreSQL advisory lock per camera is held for the whole time that
camera's worker or a verified leftover FFmpeg process is ours to manage. The
lock connection stays open until that work has stopped.
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Protocol
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import sessionmaker

from app.services.camera_ingest import (
    CameraIngest,
    CameraIngestConfig,
    camera_chunk_dir,
    ffmpeg_pid_is_alive,
    read_run_pid,
)
from app.services.camera_stream import (
    CameraNotFoundForStream,
    get_active_camera,
    list_active_cameras,
)
from app.services.cctv_feed_simulator import DEFAULT_FFMPEG
from app.services.video_chunker import DEFAULT_CHUNK_DURATION_SECONDS

logger = logging.getLogger(__name__)

SUPERVISOR_POLL_SECONDS = 5.0
RETRY_INITIAL_SECONDS = 2.0
RETRY_MAX_SECONDS = 30.0
_LOCK_NAMESPACE = 0x4461746163686169  # keeps these locks away from small integer keys


class _Lookup(Enum):
    MISSING = "missing"
    ERROR = "error"


def _signed64(value: int) -> int:
    value &= (1 << 64) - 1
    if value >= (1 << 63):
        value -= 1 << 64
    return value


def advisory_lock_keys(camera_id: UUID) -> tuple[int, int]:
    """Two session-lock keys that together cover the camera UUID."""
    value = camera_id.int
    high = _signed64(((value >> 64) ^ _LOCK_NAMESPACE) & ((1 << 64) - 1))
    low = _signed64((value ^ _LOCK_NAMESPACE) & ((1 << 64) - 1))
    return high, low


class IngestLock(Protocol):
    """Exclusive claim that another process must not record this camera."""

    def try_acquire(self, camera_id: UUID) -> bool:
        """Return True when this owner now holds the camera."""

    def release(self, camera_id: UUID) -> None:
        """Drop the claim. No-op when this owner does not hold it."""


class MemoryIngestLock:
    """In-process lock for tests. Production uses ``PostgresIngestLock``."""

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._held: set[UUID] = set()

    def try_acquire(self, camera_id: UUID) -> bool:
        with self._guard:
            if camera_id in self._held:
                return False
            self._held.add(camera_id)
            return True

    def release(self, camera_id: UUID) -> None:
        with self._guard:
            self._held.discard(camera_id)

    def holds(self, camera_id: UUID) -> bool:
        with self._guard:
            return camera_id in self._held


class PostgresIngestLock:
    """Session-level advisory locks, one detached connection per camera.

    The connection stays out of the pool until ``release``. Closing it earlier
    would drop the lock while FFmpeg is still running.
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._guard = threading.Lock()
        self._connections: dict[UUID, Connection] = {}

    def try_acquire(self, camera_id: UUID) -> bool:
        with self._guard:
            if camera_id in self._connections:
                return True
            connection = self._engine.connect()
            acquired: list[int] = []
            try:
                for key in advisory_lock_keys(camera_id):
                    locked = connection.execute(
                        text("SELECT pg_try_advisory_lock(:k)"),
                        {"k": key},
                    ).scalar()
                    if not locked:
                        self._unlock(connection, acquired)
                        connection.close()
                        return False
                    acquired.append(key)
                connection.commit()
                connection.detach()
            except Exception:
                logger.exception(
                    "Could not acquire the ingest lock for camera %s",
                    camera_id,
                )
                self._unlock(connection, acquired)
                connection.invalidate()
                connection.close()
                return False
            self._connections[camera_id] = connection
            return True

    def release(self, camera_id: UUID) -> None:
        with self._guard:
            connection = self._connections.pop(camera_id, None)
        if connection is None:
            return
        try:
            self._unlock(connection, list(advisory_lock_keys(camera_id)))
            connection.commit()
        except Exception:
            logger.exception(
                "Could not release the ingest lock for camera %s",
                camera_id,
            )
            connection.invalidate()
        finally:
            connection.close()

    @staticmethod
    def _unlock(connection: Connection, keys: list[int]) -> None:
        for key in reversed(keys):
            connection.execute(
                text("SELECT pg_advisory_unlock(:k)"),
                {"k": key},
            )


def manual_ingest_available(lock: IngestLock, camera_id: UUID) -> bool:
    """Claim a camera for a manual CLI run, or log that one is already running."""
    if lock.try_acquire(camera_id):
        return True
    logger.error(
        "Camera %s is already being recorded; not starting another ingest",
        camera_id,
    )
    return False


@dataclass(frozen=True)
class ProcessView:
    """What the supervisor could learn about a process id."""

    alive: bool | None
    command: str | None


class ProcessInspector(Protocol):
    def inspect(self, pid: int) -> ProcessView:
        """Return liveness and, when alive, the command line."""

    def terminate(self, pid: int) -> None:
        """Ask a verified process to exit."""

    def kill(self, pid: int) -> None:
        """Stop a verified process that ignored terminate."""


class PsProcessInspector:
    """Read ``ps`` and signal only the pid the caller already verified."""

    def inspect(self, pid: int) -> ProcessView:
        alive = ffmpeg_pid_is_alive(pid)
        if alive is not True:
            return ProcessView(alive=alive, command=None)
        return ProcessView(alive=True, command=_process_command(pid))

    def terminate(self, pid: int) -> None:
        os.kill(pid, signal.SIGTERM)

    def kill(self, pid: int) -> None:
        os.kill(pid, signal.SIGKILL)


def _process_command(pid: int) -> str | None:
    try:
        completed = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    command = completed.stdout.strip()
    return command or None


def command_matches_camera(
    command: str,
    *,
    camera_id: UUID,
    temp_dir: Path,
    ffmpeg_executable: str,
) -> bool:
    """True when this command is FFmpeg for this camera's segment directory."""
    parts = command.split()
    if not parts:
        return False
    executable = Path(ffmpeg_executable).name
    invoked = Path(parts[0]).name
    if invoked != executable and executable not in parts:
        return False
    if str(camera_id) in command:
        return True
    return str(temp_dir) in command


def leftover_ffmpeg_is_clear(
    temp_dir: Path,
    *,
    camera_id: UUID,
    inspector: ProcessInspector,
    ffmpeg_executable: str,
    wait_until_dead: Callable[[int], bool],
) -> bool:
    """Stop a verified leftover FFmpeg. Return False when starting would duplicate it.

    A live pid whose command line cannot be read is left alone and blocks a new
    ingest. A live pid that is some other program is a reused pid and is ignored.
    """
    if not temp_dir.is_dir():
        return True
    blocked = False
    for csv_path in sorted(temp_dir.glob("segments_*.csv")):
        pid = read_run_pid(csv_path)
        if pid is None:
            continue
        view = inspector.inspect(pid)
        if view.alive is False:
            continue
        if view.alive is not True or not view.command:
            logger.error(
                "Not starting camera %s; pid %s is alive but its command "
                "could not be verified",
                camera_id,
                pid,
            )
            blocked = True
            continue
        if not command_matches_camera(
            view.command,
            camera_id=camera_id,
            temp_dir=temp_dir,
            ffmpeg_executable=ffmpeg_executable,
        ):
            logger.info(
                "Ignoring pid %s for camera %s; it is not this camera's FFmpeg",
                pid,
                camera_id,
            )
            continue
        logger.info("Stopping leftover FFmpeg pid %s for camera %s", pid, camera_id)
        inspector.terminate(pid)
        if wait_until_dead(pid):
            continue
        inspector.kill(pid)
        if wait_until_dead(pid):
            continue
        logger.error(
            "Leftover FFmpeg pid %s for camera %s did not exit",
            pid,
            camera_id,
        )
        blocked = True
    return not blocked


Sleeper = Callable[[threading.Event, float], bool]
IngestFactory = Callable[..., CameraIngest]


def _wait_for_event(event: threading.Event, seconds: float) -> bool:
    return event.wait(timeout=seconds)


@dataclass
class _CameraRun:
    camera_id: UUID
    stream_url: str
    thread: threading.Thread
    wake: threading.Event = field(default_factory=threading.Event)
    state: threading.Lock = field(default_factory=threading.Lock)
    inactive: bool = False
    restart_url: str | None = None
    ingest: CameraIngest | None = None


class IngestSupervisor:
    """Reconcile active cameras with one ingest thread each."""

    def __init__(
        self,
        *,
        session_factory: sessionmaker,
        lock: IngestLock,
        temp_dir: Path | None = None,
        ffmpeg_executable: str = DEFAULT_FFMPEG,
        segment_duration_seconds: int = DEFAULT_CHUNK_DURATION_SECONDS,
        loop_source: bool = False,
        poll_interval_seconds: float = SUPERVISOR_POLL_SECONDS,
        retry_initial_seconds: float = RETRY_INITIAL_SECONDS,
        retry_max_seconds: float = RETRY_MAX_SECONDS,
        join_timeout_seconds: float = 10.0,
        orphan_wait_seconds: float = 5.0,
        ingest_factory: IngestFactory | None = None,
        process_inspector: ProcessInspector | None = None,
        sleeper: Sleeper | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._lock = lock
        self._temp_dir = temp_dir
        self._ffmpeg_executable = ffmpeg_executable
        self._segment_duration_seconds = segment_duration_seconds
        self._loop_source = loop_source
        self._poll_interval_seconds = poll_interval_seconds
        self._retry_initial = retry_initial_seconds
        self._retry_max = retry_max_seconds
        self._join_timeout_seconds = join_timeout_seconds
        self._orphan_wait_seconds = orphan_wait_seconds
        self._ingest_factory = ingest_factory or CameraIngest
        self._inspector = process_inspector or PsProcessInspector()
        self._sleeper = sleeper or _wait_for_event
        self._shutdown = threading.Event()
        self._runs: dict[UUID, _CameraRun] = {}
        self._held: set[UUID] = set()
        self._blocked: set[UUID] = set()
        self._lock_denied: set[UUID] = set()

    def request_shutdown(self) -> None:
        """Ask ``run`` to stop. Only sets an event, so a signal handler can call it."""
        self._shutdown.set()

    def run(self) -> int:
        """Poll until ``request_shutdown``, then stop every worker and release locks."""
        logger.info("Ingest supervisor watching active cameras")
        try:
            while not self._shutdown.is_set():
                self.reconcile_once()
                if self._shutdown.wait(self._poll_interval_seconds):
                    break
        finally:
            self._stop_and_join()
        logger.info("Ingest supervisor stopped")
        return 0

    def shutdown(self) -> None:
        """Stop workers from the caller. Used by tests and by ``run``'s exit path."""
        self.request_shutdown()
        self._stop_and_join()

    def reconcile_once(self) -> None:
        """Start missing cameras and stop archived ones.

        A failed camera list changes nothing.
        """
        if self._shutdown.is_set():
            return
        self._reap()
        desired = self._list_desired()
        if desired is None:
            return
        for camera_id, run in list(self._runs.items()):
            if camera_id not in desired:
                self._request_stop(run, inactive=True, restart_url=None)
                continue
            url = desired[camera_id]
            if run.stream_url != url and run.restart_url != url:
                self._request_stop(run, inactive=False, restart_url=url)
        for camera_id in list(self._blocked):
            if camera_id not in desired:
                self._blocked.discard(camera_id)
                self._release_lock(camera_id)
        for camera_id, url in desired.items():
            if camera_id in self._runs:
                continue
            if camera_id in self._blocked:
                self._retry_blocked(camera_id, url)
                continue
            self._start(camera_id, url)

    def _list_desired(self) -> dict[UUID, str] | None:
        try:
            db = self._session_factory()
        except Exception:
            logger.exception(
                "Cannot list active cameras; not starting or stopping workers"
            )
            return None
        try:
            cameras = list_active_cameras(db)
            return {camera.id: camera.stream_url for camera in cameras}
        except Exception:
            logger.exception(
                "Cannot list active cameras; not starting or stopping workers"
            )
            try:
                db.rollback()
            except Exception:
                logger.exception("Could not roll back after a failed camera list")
            return None
        finally:
            db.close()

    def _lookup_stream_url(self, camera_id: UUID) -> str | _Lookup:
        try:
            db = self._session_factory()
        except Exception:
            logger.exception(
                "Cannot read camera %s; not starting another ingest",
                camera_id,
            )
            return _Lookup.ERROR
        try:
            return get_active_camera(db, camera_id).stream_url
        except CameraNotFoundForStream:
            return _Lookup.MISSING
        except Exception:
            logger.exception(
                "Cannot read camera %s; not starting another ingest",
                camera_id,
            )
            try:
                db.rollback()
            except Exception:
                logger.exception("Could not roll back after a failed camera read")
            return _Lookup.ERROR
        finally:
            db.close()

    def _start(self, camera_id: UUID, stream_url: str) -> None:
        if not self._hold_lock(camera_id):
            return
        # Re-check after the lock. A permanent delete can commit while this
        # supervisor was waiting to start, and the lock is what stops the
        # two from overlapping. Starting from the earlier camera list would
        # record a camera that has already been removed.
        if not self._still_active(camera_id):
            self._release_lock(camera_id)
            return
        if not self._camera_is_clear(camera_id):
            self._blocked.add(camera_id)
            logger.error(
                "Not starting ingest for camera %s until the existing process is gone",
                camera_id,
            )
            return
        self._start_thread(camera_id, stream_url)

    def _retry_blocked(self, camera_id: UUID, stream_url: str) -> None:
        if not self._hold_lock(camera_id):
            return
        if not self._still_active(camera_id):
            self._blocked.discard(camera_id)
            self._release_lock(camera_id)
            return
        if not self._camera_is_clear(camera_id):
            return
        self._blocked.discard(camera_id)
        self._start_thread(camera_id, stream_url)

    def _start_thread(self, camera_id: UUID, stream_url: str) -> None:
        run = _CameraRun(
            camera_id=camera_id,
            stream_url=stream_url,
            thread=threading.Thread(name=f"ingest-sup-{camera_id}"),
        )
        run.thread = threading.Thread(
            target=self._camera_loop,
            args=(run,),
            name=f"ingest-sup-{camera_id}",
        )
        self._runs[camera_id] = run
        run.thread.start()
        logger.info("Started ingest for camera %s", camera_id)

    def _hold_lock(self, camera_id: UUID) -> bool:
        if camera_id in self._held:
            return True
        if not self._lock.try_acquire(camera_id):
            if camera_id not in self._lock_denied:
                logger.warning(
                    "Camera %s is already being recorded; not starting another ingest",
                    camera_id,
                )
                self._lock_denied.add(camera_id)
            return False
        self._lock_denied.discard(camera_id)
        self._held.add(camera_id)
        return True

    def _release_lock(self, camera_id: UUID) -> None:
        if camera_id not in self._held:
            return
        self._held.remove(camera_id)
        self._lock.release(camera_id)

    def _still_active(self, camera_id: UUID) -> bool:
        """True only when a fresh read still shows an active camera."""
        looked_up = self._lookup_stream_url(camera_id)
        if looked_up is _Lookup.MISSING:
            logger.info(
                "Not starting ingest for camera %s; it is archived or missing",
                camera_id,
            )
            return False
        if looked_up is _Lookup.ERROR:
            logger.error(
                "Not starting ingest for camera %s; its active state could not be read",
                camera_id,
            )
            return False
        return True

    def _camera_is_clear(self, camera_id: UUID) -> bool:
        return leftover_ffmpeg_is_clear(
            camera_chunk_dir(camera_id, self._temp_dir),
            camera_id=camera_id,
            inspector=self._inspector,
            ffmpeg_executable=self._ffmpeg_executable,
            wait_until_dead=self._wait_until_dead,
        )

    def _wait_until_dead(self, pid: int) -> bool:
        deadline = time.monotonic() + self._orphan_wait_seconds
        while True:
            if self._inspector.inspect(pid).alive is False:
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(min(0.05, max(self._orphan_wait_seconds, 0.0)))

    def _request_stop(
        self,
        run: _CameraRun,
        *,
        inactive: bool,
        restart_url: str | None,
    ) -> None:
        with run.state:
            if inactive:
                run.inactive = True
            if restart_url is not None:
                run.restart_url = restart_url
            ingest = run.ingest
        run.wake.set()
        if ingest is not None:
            ingest.stop(inactive=inactive)

    def _reap(self) -> None:
        for camera_id, run in list(self._runs.items()):
            if run.thread.is_alive():
                continue
            self._runs.pop(camera_id, None)
            self._blocked.discard(camera_id)
            self._release_lock(camera_id)

    def _stop_and_join(self) -> None:
        self._shutdown.set()
        runs = list(self._runs.values())
        for run in runs:
            self._request_stop(run, inactive=False, restart_url=None)
        for run in runs:
            run.thread.join(timeout=self._join_timeout_seconds)
            if run.thread.is_alive():
                logger.error(
                    "Ingest for camera %s did not stop; keeping its lock",
                    run.camera_id,
                )
                continue
            self._runs.pop(run.camera_id, None)
            self._release_lock(run.camera_id)
        for camera_id in list(self._blocked):
            self._blocked.discard(camera_id)
            self._release_lock(camera_id)

    def _camera_loop(self, run: _CameraRun) -> None:
        delay = self._retry_initial
        stream_url: str | None = run.stream_url
        while not self._shutdown.is_set():
            with run.state:
                if run.inactive:
                    break
                if run.restart_url is not None:
                    stream_url = run.restart_url
                    run.stream_url = stream_url
                    run.restart_url = None
            if stream_url is None:
                looked_up = self._lookup_stream_url(run.camera_id)
                if looked_up is _Lookup.ERROR:
                    if self._sleeper(run.wake, delay):
                        delay = self._retry_initial
                    else:
                        delay = min(delay * 2, self._retry_max)
                    continue
                if looked_up is _Lookup.MISSING:
                    break
                stream_url = looked_up
                run.stream_url = stream_url
            ingest = self._ingest_factory(
                self._config_for(run.camera_id, stream_url),
                session_factory=self._session_factory,
                install_signal_handlers=False,
                mark_offline_on_give_up=False,
                max_restarts=0,
            )
            with run.state:
                run.ingest = ingest
                if run.inactive or self._shutdown.is_set():
                    ingest.stop(inactive=run.inactive)
                elif run.restart_url is not None:
                    ingest.stop(inactive=False)
            try:
                ingest.run_until_signal()
            finally:
                with run.state:
                    run.ingest = None
            stream_url = None
            with run.state:
                if run.inactive or self._shutdown.is_set():
                    break
                restarting = run.restart_url is not None
            if restarting:
                delay = self._retry_initial
                continue
            if self._sleeper(run.wake, delay):
                delay = self._retry_initial
                continue
            delay = min(delay * 2, self._retry_max)

    def _config_for(self, camera_id: UUID, stream_url: str) -> CameraIngestConfig:
        return CameraIngestConfig(
            camera_id=camera_id,
            stream_url=stream_url,
            ffmpeg_executable=self._ffmpeg_executable,
            temp_dir=self._temp_dir,
            segment_duration_seconds=self._segment_duration_seconds,
            loop_source=self._loop_source,
        )


def install_supervisor_signals(supervisor: IngestSupervisor) -> None:
    """Route SIGINT and SIGTERM to ``request_shutdown`` once for the process."""

    def _handle(signum: int, _frame: object | None) -> None:
        logger.info("Received signal %s; stopping ingest supervisor", signum)
        supervisor.request_shutdown()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _handle)
        except (ValueError, OSError):
            logger.warning("Could not install handler for signal %s", sig)
