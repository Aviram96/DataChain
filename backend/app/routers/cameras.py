"""Camera CRUD routes (owner-scoped, JWT required)."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.deps import get_db
from app.deps_auth import get_current_user
from app.models.camera import Camera
from app.models.user import User
from app.schemas.camera import (
    CameraCreate,
    CameraListResponse,
    CameraPublic,
    CameraStatus,
    CameraUpdate,
)
from app.services.camera_ingest import camera_offline_reason, effective_camera_status
from app.services.camera_probe import probe_many_statuses, probe_status

router = APIRouter()

DEFAULT_PAGE_SIZE = 10
MAX_PAGE_SIZE = 50

# Default product sort: newest cameras first (documented in client/programmer stories).
CameraSort = Literal[
    "created_at_desc",
    "created_at_asc",
    "name_asc",
    "name_desc",
]
DEFAULT_SORT: CameraSort = "created_at_desc"

DUPLICATE_NAME_DETAIL = "You already have a camera with this name."


def _camera_public(camera: Camera, camera_status: CameraStatus) -> CameraPublic:
    return CameraPublic(
        id=camera.id,
        name=camera.name,
        stream_url=camera.stream_url,
        location=camera.location,
        created_at=camera.created_at,
        status=effective_camera_status(camera, camera_status),
        offline_reason=camera_offline_reason(camera, camera_status),
        ingest_offline_at=camera.ingest_offline_at,
    )


def _active_owned_filter(current_user: User):
    return (
        Camera.user_id == current_user.id,
        Camera.deleted_at.is_(None),
    )


def _get_owned_active_camera(
    camera_id: UUID,
    current_user: User,
    db: Session,
) -> Camera:
    camera = db.execute(
        select(Camera).where(
            Camera.id == camera_id,
            *_active_owned_filter(current_user),
        )
    ).scalar_one_or_none()
    if camera is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Camera not found.",
        )
    return camera


def _name_taken(
    db: Session,
    *,
    user_id: UUID,
    name: str,
    exclude_camera_id: UUID | None = None,
) -> bool:
    stmt = select(Camera.id).where(
        Camera.user_id == user_id,
        Camera.deleted_at.is_(None),
        func.lower(Camera.name) == name.lower(),
    )
    if exclude_camera_id is not None:
        stmt = stmt.where(Camera.id != exclude_camera_id)
    return db.execute(stmt).scalar_one_or_none() is not None


def _order_clause(sort: CameraSort):
    if sort == "created_at_asc":
        return Camera.created_at.asc()
    if sort == "name_asc":
        return func.lower(Camera.name).asc(), Camera.created_at.desc()
    if sort == "name_desc":
        return func.lower(Camera.name).desc(), Camera.created_at.desc()
    return Camera.created_at.desc()


@router.post(
    "",
    response_model=CameraPublic,
    status_code=status.HTTP_201_CREATED,
)
def create_camera(
    payload: CameraCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CameraPublic:
    if _name_taken(db, user_id=current_user.id, name=payload.name):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=DUPLICATE_NAME_DETAIL,
        )

    camera = Camera(
        user_id=current_user.id,
        name=payload.name,
        stream_url=payload.stream_url,
        location=payload.location,
    )
    db.add(camera)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=DUPLICATE_NAME_DETAIL,
        ) from None
    db.refresh(camera)
    return _camera_public(camera, probe_status(camera.stream_url))


@router.get("", response_model=CameraListResponse)
def list_cameras(
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    q: str | None = Query(
        None,
        max_length=200,
        description="Case-insensitive search by camera name.",
    ),
    status_filter: CameraStatus | None = Query(
        None,
        alias="status",
        description="Filter by online/offline stream reachability.",
    ),
    sort: CameraSort = Query(
        DEFAULT_SORT,
        description=(
            "Sort order. Default created_at_desc (newest first). "
            "Also: created_at_asc, name_asc, name_desc."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CameraListResponse:
    filters = list(_active_owned_filter(current_user))
    if q is not None and q.strip():
        filters.append(Camera.name.ilike(f"%{q.strip()}%"))

    order = _order_clause(sort)

    if status_filter is None:
        total = db.execute(
            select(func.count()).select_from(Camera).where(*filters)
        ).scalar_one()
        offset = (page - 1) * page_size
        cameras = (
            db.execute(
                select(Camera)
                .where(*filters)
                .order_by(*order if isinstance(order, tuple) else (order,))
                .offset(offset)
                .limit(page_size)
            )
            .scalars()
            .all()
        )
        pages = max(1, math.ceil(total / page_size)) if total else 1
        statuses = probe_many_statuses([camera.stream_url for camera in cameras])
        items = [
            _camera_public(camera, camera_status)
            for camera, camera_status in zip(cameras, statuses, strict=True)
        ]
        return CameraListResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            pages=pages,
        )

    # Status depends on live probes — load matching rows, probe, filter, then page.
    cameras = (
        db.execute(
            select(Camera)
            .where(*filters)
            .order_by(*order if isinstance(order, tuple) else (order,))
        )
        .scalars()
        .all()
    )
    statuses = probe_many_statuses([camera.stream_url for camera in cameras])
    matched: list[tuple[Camera, CameraStatus]] = []
    for camera, probed in zip(cameras, statuses, strict=True):
        camera_status = effective_camera_status(camera, probed)
        if camera_status == status_filter:
            matched.append((camera, probed))
    total = len(matched)
    pages = max(1, math.ceil(total / page_size)) if total else 1
    offset = (page - 1) * page_size
    page_rows = matched[offset : offset + page_size]
    items = [
        _camera_public(camera, camera_status) for camera, camera_status in page_rows
    ]
    return CameraListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


@router.get("/{camera_id}", response_model=CameraPublic)
def get_camera(
    camera_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CameraPublic:
    camera = _get_owned_active_camera(camera_id, current_user, db)
    return _camera_public(camera, probe_status(camera.stream_url))


@router.patch("/{camera_id}", response_model=CameraPublic)
def update_camera(
    camera_id: UUID,
    payload: CameraUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CameraPublic:
    camera = _get_owned_active_camera(camera_id, current_user, db)
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields to update.",
        )
    if "name" in updates and _name_taken(
        db,
        user_id=current_user.id,
        name=updates["name"],
        exclude_camera_id=camera.id,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=DUPLICATE_NAME_DETAIL,
        )
    for field, value in updates.items():
        setattr(camera, field, value)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=DUPLICATE_NAME_DETAIL,
        ) from None
    db.refresh(camera)
    return _camera_public(camera, probe_status(camera.stream_url))


@router.delete(
    "/{camera_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_camera(
    camera_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Soft-delete: hide from the dashboard; keep the row for video history."""
    camera = _get_owned_active_camera(camera_id, current_user, db)
    camera.deleted_at = datetime.now(timezone.utc)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
