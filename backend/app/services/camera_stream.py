"""Resolve registered camera streams for ingest (Slice B / CP-B.P5).

``attach_camera_stream`` returns an active camera's ``stream_url``. Continuous
FFmpeg receive for those URLs lives in Slice C (``camera_ingest``).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.camera import Camera


class CameraStreamError(Exception):
    """Raised when a camera stream cannot be attached for ingest."""


class CameraNotFoundForStream(CameraStreamError):
    """No active (non-deleted) camera exists for the given id."""


def get_active_camera(db: Session, camera_id: UUID) -> Camera:
    """Return an active camera row or raise ``CameraNotFoundForStream``."""
    camera = db.execute(
        select(Camera).where(
            Camera.id == camera_id,
            Camera.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if camera is None:
        raise CameraNotFoundForStream(f"Active camera not found: {camera_id}")
    return camera


def list_active_cameras(db: Session) -> list[Camera]:
    """Return all non-deleted cameras, oldest first."""
    return list(
        db.execute(
            select(Camera)
            .where(Camera.deleted_at.is_(None))
            .order_by(Camera.created_at.asc())
        )
        .scalars()
        .all()
    )


def attach_camera_stream(db: Session, camera_id: UUID) -> str:
    """Return the stream URL for an active registered camera.

    Callers (Slice C ingest) use this URL with FFmpeg. Soft-deleted cameras
    are not attachable.
    """
    return get_active_camera(db, camera_id).stream_url
