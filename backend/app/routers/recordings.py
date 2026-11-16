"""Owner-scoped recording search, download, and playback."""

from __future__ import annotations

import json
import math
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import anyio
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse, JSONResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.types import Receive, Scope, Send

from app.deps import get_db
from app.deps_auth import get_current_user
from app.models.camera import Camera
from app.models.user import User
from app.models.video_record import VideoRecord
from app.schemas.recording import (
    DownloadSegmentPublic,
    DownloadVerificationReport,
    PlaybackDenial,
    PlaybackExcludedPublic,
    PlaybackIntervalPublic,
    PlaybackSegmentPublic,
    PlaybackStatus,
    VideoRecordListResponse,
    VideoRecordPublic,
)
from app.services.recording_download import (
    MAX_DOWNLOAD_SEGMENTS,
    RecordingDownloadError,
    assemble_verified_files,
    download_filename,
)
from app.services.recording_verification import (
    RecordingVerification,
    RecordingVerificationError,
    verify_recording_range,
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


class _CleanupFileResponse(FileResponse):
    """Serve one verified file, then delete its temp directory.

    Cleanup runs after a finished response and when sending raises, including
    a client that disconnects mid-stream.
    """

    def __init__(
        self,
        path: Path,
        *,
        cleanup_dir: str,
        media_type: str,
        filename: str,
        content_disposition_type: str,
    ) -> None:
        super().__init__(
            path=path,
            media_type=media_type,
            filename=filename,
            content_disposition_type=content_disposition_type,
        )
        self._cleanup_dir = cleanup_dir

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            _cleanup_dir(self._cleanup_dir)


class _VerifiedDownloadResponse(Response):
    """Stream a verification report plus one video, then delete the temp dir.

    Cleanup runs after a finished response and when sending raises, including
    a client that disconnects mid-stream. The video part is only the file the
    caller already assembled from verified segments.
    """

    def __init__(
        self,
        *,
        video_path: Path,
        report_json: dict[str, object],
        filename: str,
        cleanup_dir: str,
    ) -> None:
        self._video_path = video_path
        self._report_bytes = json.dumps(report_json).encode()
        self._filename = (
            filename.replace('"', "").replace("\r", "").replace("\n", "")
        )
        self._cleanup_dir = cleanup_dir
        self._boundary = f"datachain{uuid4().hex}"
        super().__init__(
            media_type=f"multipart/form-data; boundary={self._boundary}",
            status_code=status.HTTP_200_OK,
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        del receive
        boundary = self._boundary.encode()
        filename = self._filename
        video_headers = (
            f'Content-Disposition: form-data; name="video"; filename="{filename}"\r\n'
            "Content-Type: video/mp4\r\n\r\n"
        ).encode()
        preamble = (
            b"--"
            + boundary
            + b"\r\n"
            + b'Content-Disposition: form-data; name="report"\r\n'
            + b"Content-Type: application/json\r\n\r\n"
            + self._report_bytes
            + b"\r\n--"
            + boundary
            + b"\r\n"
            + video_headers
        )
        closing = b"\r\n--" + boundary + b"--\r\n"
        try:
            await send(
                {
                    "type": "http.response.start",
                    "status": status.HTTP_200_OK,
                    "headers": [
                        [b"content-type", (self.media_type or "").encode()],
                        [b"cache-control", b"no-store"],
                    ],
                }
            )
            await send(
                {"type": "http.response.body", "body": preamble, "more_body": True}
            )
            async with await anyio.open_file(self._video_path, "rb") as handle:
                while True:
                    chunk = await handle.read(64 * 1024)
                    if not chunk:
                        break
                    await send(
                        {
                            "type": "http.response.body",
                            "body": chunk,
                            "more_body": True,
                        }
                    )
            await send(
                {"type": "http.response.body", "body": closing, "more_body": False}
            )
        finally:
            _cleanup_dir(self._cleanup_dir)


def _download_work_dir() -> Path:
    root = resolve_temp_dir() / "downloads"
    root.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="range-", dir=root))


def _playback_work_dir() -> Path:
    root = resolve_temp_dir() / "playback"
    root.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="playback-", dir=root))


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


@router.get("/{camera_id}/recordings/download", response_model=None)
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
) -> Response:
    """Verify every overlapping segment, then serve only verified files."""
    _get_owned_active_camera(camera_id, current_user, db)
    window_start, window_end = _window_or_400(started_at, ended_at)
    assert window_start is not None and window_end is not None
    filters = _recording_filters(camera_id, window_start, window_end)
    total = db.execute(
        select(func.count()).select_from(VideoRecord).where(*filters)
    ).scalar_one()
    if total > MAX_DOWNLOAD_SEGMENTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Choose a range of 24 hours or less to download.",
        )

    work_dir = _download_work_dir()
    try:
        report = verify_recording_range(
            db,
            camera_id,
            window_start,
            window_end,
            work_dir=work_dir,
        )
    except RecordingVerificationError as exc:
        _cleanup_dir(str(work_dir))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=exc.detail,
        ) from exc
    except Exception:
        _cleanup_dir(str(work_dir))
        raise

    safe = [
        item
        for item in report.eligible
        if _file_stays_in_dir(item.path, work_dir)
    ]
    if len(safe) != len(report.eligible):
        _cleanup_dir(str(work_dir))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                "Verification could not be completed because the file "
                "was not available."
            ),
        )

    payload = _download_report(db, camera_id, report, served=bool(safe))
    if not safe:
        _cleanup_dir(str(work_dir))
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=payload.model_dump(mode="json"),
            headers={"Cache-Control": "no-store"},
        )

    try:
        output = assemble_verified_files(
            [item.path for item in safe],
            work_dir,
        )
    except RecordingDownloadError as exc:
        _cleanup_dir(str(work_dir))
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except Exception:
        _cleanup_dir(str(work_dir))
        raise

    if not _file_stays_in_dir(output, work_dir):
        _cleanup_dir(str(work_dir))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not combine recordings into one file.",
        )

    return _VerifiedDownloadResponse(
        video_path=output,
        report_json=payload.model_dump(mode="json"),
        filename=download_filename(window_start, window_end),
        cleanup_dir=str(work_dir),
    )


@router.get(
    "/{camera_id}/recordings/{record_id}/playback",
    response_model=None,
)
def play_recording(
    camera_id: UUID,
    record_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> _CleanupFileResponse | JSONResponse:
    """Verify one owned segment, then stream it. Failures return JSON, not media."""
    _get_owned_active_camera(camera_id, current_user, db)
    record = db.execute(
        select(VideoRecord).where(
            VideoRecord.id == record_id,
            VideoRecord.camera_id == camera_id,
        )
    ).scalar_one_or_none()
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recording not found.",
        )

    work_dir = _playback_work_dir()
    try:
        report = verify_recording_range(
            db,
            camera_id,
            record.started_at,
            record.ended_at,
            work_dir=work_dir,
        )
    except RecordingVerificationError as exc:
        _cleanup_dir(str(work_dir))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=exc.detail,
        ) from exc
    except Exception:
        _cleanup_dir(str(work_dir))
        raise

    playable = next(
        (item for item in report.eligible if item.video_record_id == record.id),
        None,
    )
    if playable is not None and _file_stays_in_dir(playable.path, work_dir):
        return _CleanupFileResponse(
            path=playable.path,
            media_type="video/mp4",
            filename=download_filename(record.started_at, record.ended_at),
            content_disposition_type="inline",
            cleanup_dir=str(work_dir),
        )

    denial = _playback_denial(report, record.id)
    _cleanup_dir(str(work_dir))
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content=denial.model_dump(mode="json"),
    )


def _file_stays_in_dir(path: Path, work_dir: Path) -> bool:
    try:
        path.resolve().relative_to(work_dir.resolve())
    except (OSError, ValueError):
        return False
    return path.is_file()


def _playback_denial(report: RecordingVerification, record_id: UUID) -> PlaybackDenial:
    segment = next(
        (item for item in report.segments if item.video_record_id == record_id),
        None,
    )
    if segment is None:
        overall: PlaybackStatus = "missing" if report.missing_intervals else "failed"
        detail = (
            report.missing_intervals[0].detail
            if report.missing_intervals
            else "This recording could not be verified."
        )
    elif segment.status == "verified":
        overall = "failed"
        detail = (
            "Verification could not be completed because the file was not available."
        )
    else:
        overall = segment.status
        detail = segment.detail
    return PlaybackDenial(
        overall=overall,
        detail=detail,
        segments=[
            PlaybackSegmentPublic(
                video_record_id=item.video_record_id,
                started_at=item.started_at,
                ended_at=item.ended_at,
                status=item.status,
                detail=item.detail,
            )
            for item in report.segments
        ],
        missing_intervals=[
            PlaybackIntervalPublic(
                started_at=item.started_at,
                ended_at=item.ended_at,
                detail=item.detail,
            )
            for item in report.missing_intervals
        ],
        excluded_intervals=[
            PlaybackExcludedPublic(
                started_at=item.started_at,
                ended_at=item.ended_at,
                detail=item.detail,
                status=item.status,
                video_record_id=item.video_record_id,
            )
            for item in report.excluded_intervals
        ],
    )


def _download_report(
    db: Session,
    camera_id: UUID,
    report: RecordingVerification,
    *,
    served: bool,
) -> DownloadVerificationReport:
    tx_hashes = _tx_hashes(
        db,
        camera_id,
        [item.video_record_id for item in report.segments],
    )
    discontinuous = served and bool(
        report.missing_intervals or report.excluded_intervals
    )
    if not served:
        detail = (
            "No verified video is available for this range, "
            "so nothing was downloaded."
        )
    elif discontinuous:
        detail = (
            "The download includes only verified portions. "
            "Gaps and excluded intervals were left out, so this file "
            "is not one continuous recording."
        )
    else:
        detail = "Every segment in this range is verified."
    return DownloadVerificationReport(
        overall=report.overall,
        detail=detail,
        discontinuous=discontinuous,
        segments=[
            DownloadSegmentPublic(
                video_record_id=item.video_record_id,
                started_at=item.started_at,
                ended_at=item.ended_at,
                status=item.status,
                detail=item.detail,
                tx_hash=tx_hashes.get(item.video_record_id),
            )
            for item in report.segments
        ],
        missing_intervals=[
            PlaybackIntervalPublic(
                started_at=item.started_at,
                ended_at=item.ended_at,
                detail=item.detail,
            )
            for item in report.missing_intervals
        ],
        excluded_intervals=[
            PlaybackExcludedPublic(
                started_at=item.started_at,
                ended_at=item.ended_at,
                detail=item.detail,
                status=item.status,
                video_record_id=item.video_record_id,
            )
            for item in report.excluded_intervals
        ],
    )


def _tx_hashes(
    db: Session,
    camera_id: UUID,
    record_ids: list[UUID],
) -> dict[UUID, str | None]:
    if not record_ids:
        return {}
    rows = db.execute(
        select(VideoRecord.id, VideoRecord.tx_hash).where(
            VideoRecord.camera_id == camera_id,
            VideoRecord.id.in_(record_ids),
        )
    ).all()
    return {row.id: row.tx_hash for row in rows}
