"""Owner-scoped verification attempt audit trail (Slice E / CP-E.P8).

Persists the in-browser report. Does not call getSegment / Web3.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.deps import get_db
from app.deps_auth import get_current_user
from app.models.camera import Camera
from app.models.user import User
from app.models.verification_attempt import (
    VerificationAttempt,
    VerificationAttemptMinute,
)
from app.schemas.verification import (
    VerificationAttemptCreate,
    VerificationAttemptListResponse,
    VerificationAttemptPublic,
    VerificationAttemptSummary,
)

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
    started_at: datetime,
    ended_at: datetime,
) -> tuple[datetime, datetime]:
    window_start = _as_utc(started_at)
    window_end = _as_utc(ended_at)
    if window_end <= window_start:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="End time must be after start time.",
        )
    return window_start, window_end


@router.post(
    "/{camera_id}/verification-attempts",
    response_model=VerificationAttemptPublic,
    status_code=status.HTTP_201_CREATED,
)
def create_verification_attempt(
    camera_id: UUID,
    payload: VerificationAttemptCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> VerificationAttempt:
    _get_owned_active_camera(camera_id, current_user, db)
    window_start, window_end = _window_or_400(payload.started_at, payload.ended_at)

    attempt = VerificationAttempt(
        user_id=current_user.id,
        camera_id=camera_id,
        started_at=window_start,
        ended_at=window_end,
        scope=payload.scope,
        overall_status=payload.overall_status,
        created_at=datetime.now(timezone.utc),
    )
    for minute in payload.minutes:
        attempt.minutes.append(
            VerificationAttemptMinute(
                started_at=_as_utc(minute.started_at),
                status=minute.status,
                detail=minute.detail,
                video_record_id=minute.video_record_id,
            )
        )
    db.add(attempt)
    db.commit()
    loaded = db.execute(
        select(VerificationAttempt)
        .options(selectinload(VerificationAttempt.minutes))
        .where(VerificationAttempt.id == attempt.id)
    ).scalar_one()
    return loaded


@router.get(
    "/{camera_id}/verification-attempts",
    response_model=VerificationAttemptListResponse,
)
def list_verification_attempts(
    camera_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> VerificationAttemptListResponse:
    _get_owned_active_camera(camera_id, current_user, db)
    filters = [
        VerificationAttempt.camera_id == camera_id,
        VerificationAttempt.user_id == current_user.id,
    ]
    total = db.execute(
        select(func.count()).select_from(VerificationAttempt).where(*filters)
    ).scalar_one()
    offset = (page - 1) * page_size
    rows = (
        db.execute(
            select(VerificationAttempt)
            .where(*filters)
            .order_by(VerificationAttempt.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        .scalars()
        .all()
    )
    pages = max(1, math.ceil(total / page_size)) if total else 1
    return VerificationAttemptListResponse(
        items=[VerificationAttemptSummary.model_validate(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )
