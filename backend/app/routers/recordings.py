"""Owner-scoped recording search and download (Slice E / CP-E.P1–P2, P10)."""

from __future__ import annotations

import math
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.deps import get_db
from app.deps_auth import get_current_user
from app.models.camera import Camera
from app.models.user import User
from app.models.video_record import VideoRecord
from app.schemas.recording import VideoRecordListResponse, VideoRecordPublic
from app.services.recording_download import (
    MAX_DOWNLOAD_SEGMENTS,
    RecordingDownloadError,
    assemble_range_download,
    download_filename,
)
from app.services.video_chunker import resolve_temp_dir

router = APIRouter()

DEFAULT_PAGE_SIZE = 10
MAX_PAGE_SIZE = 50


def _as_utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _get_owned_active_camera(
    camera_id: UUID,
    current_user: User,
    db: Session,
) -> Camera:
    camera = db.execute(
        select(Camera).where(
            Camera.id == camera_id,
            Camera.user_id == current_user.id,
            Camera.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if camera is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Camera not found.",
        )
    return camera


def _window_or_400(
    started_at: datetime | None,
    ended_at: datetime | None,
) -> tuple[datetime | None, datetime | None]:
    window_start = _as_utc(started_at) if started_at is not None else None
    window_end = _as_utc(ended_at) if ended_at is not None else None
    if (
        window_start is not None
        and window_end is not None
        and window_end <= window_start
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="End time must be after start time.",
        )
    return window_start, window_end


def _recording_filters(
    camera_id: UUID,
    window_start: datetime | None,
    window_end: datetime | None,
) -> list[object]:
    filters: list[object] = [VideoRecord.camera_id == camera_id]
    if window_start is not None:
        filters.append(VideoRecord.ended_at > window_start)
    if window_end is not None:
        filters.append(VideoRecord.started_at < window_end)
    return filters


def _cleanup_dir(path: str) -> None:
    shutil.rmtree(path, ignore_errors=True)


@router.get(
    "/{camera_id}/recordings",
    response_model=VideoRecordListResponse,
)
def list_recordings(
    camera_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    started_at: datetime | None = Query(
        None,
        description="Window start (inclusive). Segments overlapping the window.",
    ),
    ended_at: datetime | None = Query(
        None,
        description="Window end (exclusive). Segments overlapping the window.",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> VideoRecordListResponse:
    _get_owned_active_camera(camera_id, current_user, db)
    window_start, window_end = _window_or_400(started_at, ended_at)
    filters = _recording_filters(camera_id, window_start, window_end)

    total = db.execute(
        select(func.count()).select_from(VideoRecord).where(*filters)
    ).scalar_one()
    offset = (page - 1) * page_size
    rows = (
        db.execute(
            select(VideoRecord)
            .where(*filters)
            .order_by(VideoRecord.started_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        .scalars()
        .all()
    )
    pages = max(1, math.ceil(total / page_size)) if total else 1
    return VideoRecordListResponse(
        items=[VideoRecordPublic.model_validate(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


@router.get("/{camera_id}/recordings/download")
def download_recordings(
    camera_id: UUID,
    started_at: datetime = Query(
        ...,
        description="Window start (inclusive). Segments overlapping the window.",
    ),
    ended_at: datetime = Query(
        ...,
        description="Window end (exclusive). Segments overlapping the window.",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FileResponse:
    _get_owned_active_camera(camera_id, current_user, db)
    window_start, window_end = _window_or_400(started_at, ended_at)
    assert window_start is not None and window_end is not None
    filters = _recording_filters(camera_id, window_start, window_end)
    rows = (
        db.execute(
            select(VideoRecord)
            .where(*filters)
            .order_by(VideoRecord.started_at.asc())
        )
        .scalars()
        .all()
    )
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No recordings in that range.",
        )
    if len(rows) > MAX_DOWNLOAD_SEGMENTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Choose a range of 24 hours or less to download.",
        )

    downloads_root = resolve_temp_dir() / "downloads"
    downloads_root.mkdir(parents=True, exist_ok=True)
    work_dir = Path(tempfile.mkdtemp(prefix="range-", dir=downloads_root))
    try:
        output = assemble_range_download(
            [row.ipfs_cid for row in rows],
            work_dir,
        )
    except RecordingDownloadError as exc:
        _cleanup_dir(str(work_dir))
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except Exception:
        _cleanup_dir(str(work_dir))
        raise

    return FileResponse(
        path=output,
        media_type="video/mp4",
        filename=download_filename(window_start, window_end),
        background=BackgroundTask(_cleanup_dir, str(work_dir)),
    )
