"""Permanently delete an archived camera that has no saved footage.

Only the camera row is removed. Recordings, verification history, IPFS pins,
local files, and blockchain anchors are left untouched. A camera that still
has any of that dependent data is rejected before the row is deleted.
"""

from __future__ import annotations

import logging
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn
from uuid import UUID

from sqlalchemy import delete as sql_delete
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.camera import Camera
from app.models.verification_attempt import VerificationAttempt
from app.models.video_record import VideoRecord
from app.services.camera_ingest import ffmpeg_pid_is_alive
from app.services.cctv_feed_simulator import DEFAULT_FFMPEG
from app.services.ingest_supervisor import advisory_lock_keys, command_matches_camera
from app.services.video_chunker import BACKEND_ROOT, resolve_temp_dir

logger = logging.getLogger(__name__)

NOT_FOUND = "Camera not found."
NOT_ARCHIVED = "Only archived cameras can be permanently deleted."
NAME_MISMATCH = "Camera name confirmation does not match."
HAS_DEPENDENT_DATA = (
    "This camera contains saved recordings or related data "
    "and cannot be permanently deleted."
)
STILL_RECORDING = (
    "This camera is still recording. Try again after recording has stopped."
)
_PS_TIMEOUT_SECONDS = 2

CommandLister = Callable[[], list[str] | None]


class PermanentDeleteError(Exception):
    """The camera was not deleted. ``status_code`` is the HTTP result."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class PermanentDeleteOutcome:
    camera_id: UUID
    message: str = "Camera deleted."

    @property
    def deleted(self) -> bool:
        return True


def temp_root_for_cleanup() -> Path:
    """Directory whose per-camera folder may still hold a live writer."""
    return resolve_temp_dir()


def quarantine_root_for_cleanup() -> Path:
    """Optional per-camera directory checked for a live writer."""
    return (BACKEND_ROOT / "quarantine").resolve()


def list_process_commands() -> list[str] | None:
    """Return process command lines, or None when the check cannot tell.

    Command lines are not logged. They can contain a stream URL.
    """
    try:
        completed = subprocess.run(
            ["ps", "-ax", "-o", "command="],
            check=False,
            capture_output=True,
            text=True,
            timeout=_PS_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return [line.strip() for line in completed.stdout.splitlines() if line.strip()]


def permanently_delete_camera(
    db: Session,
    *,
    camera_id: UUID,
    owner_id: UUID,
    confirm_name: str,
    temp_root: Path | None = None,
    quarantine_root: Path | None = None,
    command_lister: CommandLister | None = None,
) -> PermanentDeleteOutcome:
    """Delete one owned archived camera that has no dependent rows."""
    roots = _roots(temp_root, quarantine_root)
    lister = command_lister if command_lister is not None else list_process_commands

    camera = _load_owned(db, camera_id, owner_id)
    if camera is None:
        _refuse(db, 404, NOT_FOUND)
    if camera.deleted_at is None:
        _refuse(db, 409, NOT_ARCHIVED)
    if confirm_name != camera.name:
        _refuse(db, 400, NAME_MISMATCH)
    if _has_dependent_data(db, camera.id):
        _refuse(db, 409, HAS_DEPENDENT_DATA)
    if not try_hold_ingest_locks(db, camera.id):
        _refuse(db, 409, STILL_RECORDING)
    if _recording_is_active(camera.id, roots, lister):
        _refuse(db, 409, STILL_RECORDING)
    if _has_dependent_data(db, camera.id):
        _refuse(db, 409, HAS_DEPENDENT_DATA)

    try:
        db.execute(
            sql_delete(Camera).where(
                Camera.id == camera.id,
                Camera.user_id == owner_id,
                Camera.deleted_at.is_not(None),
            )
        )
        db.flush()
    except IntegrityError:
        _refuse(db, 409, HAS_DEPENDENT_DATA)
    remaining = db.scalar(
        select(func.count()).select_from(Camera).where(Camera.id == camera.id)
    )
    if remaining:
        _refuse(db, 409, NOT_ARCHIVED)
    db.commit()
    logger.info("Permanently deleted empty archived camera %s", camera_id)
    return PermanentDeleteOutcome(camera_id=camera_id)


def try_hold_ingest_locks(db: Session, camera_id: UUID) -> bool:
    """Hold this camera's ingest locks until the transaction ends.

    Returns False when recording already holds either key. SQLite tests do
    not take advisory locks unless the caller replaces this function.
    """
    if db.get_bind().dialect.name != "postgresql":
        return True
    for key in advisory_lock_keys(camera_id):
        locked = db.execute(
            text("SELECT pg_try_advisory_xact_lock(:k)"),
            {"k": key},
        ).scalar()
        if not locked:
            return False
    return True


def _has_dependent_data(db: Session, camera_id: UUID) -> bool:
    recordings = _count(db, VideoRecord, VideoRecord.camera_id == camera_id)
    attempts = _count(
        db, VerificationAttempt, VerificationAttempt.camera_id == camera_id
    )
    return recordings > 0 or attempts > 0


def _recording_is_active(
    camera_id: UUID,
    roots: tuple[Path, Path],
    command_lister: CommandLister,
) -> bool:
    """True when a writer may still be using this camera, or we cannot tell."""
    commands = command_lister()
    if commands is None:
        return True
    for root in roots:
        directory = root / str(camera_id)
        pid_state = _pid_files_are_busy(directory, camera_id)
        if pid_state is not False:
            return True
        for command in commands:
            if command_matches_camera(
                command,
                camera_id=camera_id,
                temp_dir=directory,
                ffmpeg_executable=DEFAULT_FFMPEG,
            ):
                return True
    return False


def _pid_files_are_busy(directory: Path, camera_id: UUID) -> bool | None:
    """True when a recorded pid is a live writer, None when the check is unsure.

    False means every recorded pid is gone or belongs to some other program.
    A symlink is not followed and is not treated as a writer.
    """
    if not directory.exists():
        return False
    if directory.is_symlink() or not directory.is_dir():
        return False
    for pid_file in directory.glob("*.pid"):
        pid = _read_pid_file(pid_file)
        if pid is None:
            return None
        alive = ffmpeg_pid_is_alive(pid)
        if alive is None:
            return None
        if alive is False:
            continue
        command = _command_for_pid(pid)
        if command is None:
            return None
        if command_matches_camera(
            command,
            camera_id=camera_id,
            temp_dir=directory,
            ffmpeg_executable=DEFAULT_FFMPEG,
        ):
            return True
    return False


def _command_for_pid(pid: int) -> str | None:
    try:
        completed = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            check=False,
            capture_output=True,
            text=True,
            timeout=_PS_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    command = completed.stdout.strip()
    return command or None


def _read_pid_file(path: Path) -> int | None:
    try:
        raw = path.read_text(encoding="utf-8").strip()
        pid = int(raw)
    except (OSError, ValueError):
        return None
    if pid <= 0:
        return None
    return pid


def _load_owned(db: Session, camera_id: UUID, owner_id: UUID) -> Camera | None:
    stmt = select(Camera).where(Camera.id == camera_id, Camera.user_id == owner_id)
    if db.get_bind().dialect.name == "postgresql":
        stmt = stmt.with_for_update()
    return db.execute(stmt).scalar_one_or_none()


def _count(db: Session, model: type, *filters: object) -> int:
    stmt = select(func.count()).select_from(model)
    if filters:
        stmt = stmt.where(*filters)
    value = db.scalar(stmt)
    return int(value or 0)


def _roots(
    temp_root: Path | None,
    quarantine_root: Path | None,
) -> tuple[Path, Path]:
    temp = temp_root if temp_root is not None else temp_root_for_cleanup()
    quarantine = (
        quarantine_root
        if quarantine_root is not None
        else quarantine_root_for_cleanup()
    )
    return temp, quarantine


def _refuse(db: Session, status_code: int, detail: str) -> NoReturn:
    db.rollback()
    raise PermanentDeleteError(status_code, detail)
