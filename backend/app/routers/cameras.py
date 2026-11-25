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
    PermanentDeleteRequest,
    PermanentDeleteResponse,
)
from app.services.camera_deletion import (
    PermanentDeleteError,
    permanently_delete_camera,
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
ALREADY_ARCHIVED_DETAIL = "This camera is already archived."
NOT_ARCHIVED_DETAIL = "This camera is not archived."
ARCHIVED_EDIT_DETAIL = "Archived cameras cannot be edited."


def _camera_public(camera: Camera, camera_status: CameraStatus) -> CameraPublic:
    """Build the API camera. Archived is a lifecycle, not an offline status."""
    if camera.deleted_at is not None:
        return CameraPublic(
            id=camera.id,
            name=camera.name,
            stream_url=camera.stream_url,
            location=camera.location,
            created_at=camera.created_at,
            status="offline",
            offline_reason=None,
            ingest_offline_at=None,
            lifecycle="archived",
            archived_at=camera.deleted_at,
        )
    return CameraPublic(
        id=camera.id,
        name=camera.name,
        stream_url=camera.stream_url,
        location=camera.location,
        created_at=camera.created_at,
        status=effective_camera_status(camera, camera_status),
        offline_reason=camera_offline_reason(camera, camera_status),
        ingest_offline_at=camera.ingest_offline_at,
        lifecycle="active",
        archived_at=None,
    )


def _active_owned_filter(current_user: User):
    return (
        Camera.user_id == current_user.id,
        Camera.deleted_at.is_(None),
    )


def _get_owned_camera(
    camera_id: UUID,
    current_user: User,
    db: Session,
    *,
    lock: bool = False,
) -> Camera:
    """Return the owner's camera, archived or active. Other users get 404.

    ``lock`` takes a PostgreSQL row lock so archive, restore, and permanent
    deletion cannot commit over each other. SQLite tests keep the unlocked
    read because that dialect rejects FOR UPDATE.
    """
    stmt = select(Camera).where(
        Camera.id == camera_id,
        Camera.user_id == current_user.id,
    )
    if lock and db.get_bind().dialect.name == "postgresql":
        stmt = stmt.with_for_update()
    camera = db.execute(stmt).scalar_one_or_none()
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


@router.get("/archived", response_model=CameraListResponse)
def list_archived_cameras(
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    q: str | None = Query(
        None,
        max_length=200,
        description="Case-insensitive search by camera name.",
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
    """List the caller's archived cameras. Active cameras are not included."""
    filters = [
        Camera.user_id == current_user.id,
        Camera.deleted_at.is_not(None),
    ]
    if q is not None and q.strip():
        filters.append(Camera.name.ilike(f"%{q.strip()}%"))
    order = _order_clause(sort)
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
    items = [_camera_public(camera, "offline") for camera in cameras]
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
    """Owner can read an active or archived camera. Other users get 404."""
    camera = _get_owned_camera(camera_id, current_user, db)
    if camera.deleted_at is not None:
        return _camera_public(camera, "offline")
    return _camera_public(camera, probe_status(camera.stream_url))


@router.patch("/{camera_id}", response_model=CameraPublic)
def update_camera(
    camera_id: UUID,
    payload: CameraUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CameraPublic:
    camera = _get_owned_camera(camera_id, current_user, db)
    if camera.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ARCHIVED_EDIT_DETAIL,
        )
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


def _archive_owned_camera(
    camera_id: UUID,
    current_user: User,
    db: Session,
) -> Camera:
    """Hide the camera and mark it archived. Does not touch recordings."""
    camera = _get_owned_camera(camera_id, current_user, db, lock=True)
    if camera.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ALREADY_ARCHIVED_DETAIL,
        )
    camera.deleted_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(camera)
    return camera


@router.post("/{camera_id}/archive", response_model=CameraPublic)
def archive_camera(
    camera_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CameraPublic:
    """Archive an active camera. Recording stops; the row and its footage stay."""
    camera = _archive_owned_camera(camera_id, current_user, db)
    return _camera_public(camera, "offline")


@router.post("/{camera_id}/restore", response_model=CameraPublic)
def restore_camera(
    camera_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CameraPublic:
    """Clear archive on the same camera row. Does not start recording."""
    camera = _get_owned_camera(camera_id, current_user, db, lock=True)
    if camera.deleted_at is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=NOT_ARCHIVED_DETAIL,
        )
    if _name_taken(db, user_id=current_user.id, name=camera.name):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=DUPLICATE_NAME_DETAIL,
        )
    camera.deleted_at = None
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


@router.post(
    "/{camera_id}/permanent-delete",
    response_model=PermanentDeleteResponse,
)
def permanently_delete_camera_route(
    camera_id: UUID,
    payload: PermanentDeleteRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PermanentDeleteResponse:
    """Delete one empty archived camera owned by the caller.

    Archive and restore are unchanged. Recordings, verification history,
    IPFS objects, local files, and blockchain anchors are not modified.
    """
    try:
        outcome = permanently_delete_camera(
            db,
            camera_id=camera_id,
            owner_id=current_user.id,
            confirm_name=payload.confirm_name,
        )
    except PermanentDeleteError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.detail,
        ) from None
    return PermanentDeleteResponse(
        camera_id=outcome.camera_id,
        deleted=outcome.deleted,
        message=outcome.message,
    )


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
    """Archive alias. Keeps the row and recordings; does not permanently delete."""
    _archive_owned_camera(camera_id, current_user, db)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
