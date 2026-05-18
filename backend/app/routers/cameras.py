"""Camera CRUD routes (owner-scoped, JWT required)."""

from __future__ import annotations

import math
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.deps import get_db
from app.deps_auth import get_current_user
from app.models.camera import Camera
from app.models.user import User
from app.schemas.camera import (
    CameraCreate,
    CameraListResponse,
    CameraPublic,
    CameraUpdate,
)

router = APIRouter()

DEFAULT_PAGE_SIZE = 10
MAX_PAGE_SIZE = 50


def _get_owned_camera(
    camera_id: UUID,
    current_user: User,
    db: Session,
) -> Camera:
    camera = db.execute(
        select(Camera).where(
            Camera.id == camera_id,
            Camera.user_id == current_user.id,
        )
    ).scalar_one_or_none()
    if camera is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Camera not found.",
        )
    return camera


@router.post(
    "",
    response_model=CameraPublic,
    status_code=status.HTTP_201_CREATED,
)
def create_camera(
    payload: CameraCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Camera:
    camera = Camera(
        user_id=current_user.id,
        name=payload.name,
        stream_url=payload.stream_url,
        location=payload.location,
    )
    db.add(camera)
    db.commit()
    db.refresh(camera)
    return camera


@router.get("", response_model=CameraListResponse)
def list_cameras(
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CameraListResponse:
    total = db.execute(
        select(func.count())
        .select_from(Camera)
        .where(Camera.user_id == current_user.id)
    ).scalar_one()

    offset = (page - 1) * page_size
    cameras = (
        db.execute(
            select(Camera)
            .where(Camera.user_id == current_user.id)
            .order_by(Camera.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        .scalars()
        .all()
    )

    pages = max(1, math.ceil(total / page_size)) if total else 1
    return CameraListResponse(
        items=cameras,
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
) -> Camera:
    return _get_owned_camera(camera_id, current_user, db)


@router.patch("/{camera_id}", response_model=CameraPublic)
def update_camera(
    camera_id: UUID,
    payload: CameraUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Camera:
    camera = _get_owned_camera(camera_id, current_user, db)
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields to update.",
        )
    for field, value in updates.items():
        setattr(camera, field, value)
    db.commit()
    db.refresh(camera)
    return camera


@router.delete("/{camera_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_camera(
    camera_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    camera = _get_owned_camera(camera_id, current_user, db)
    db.delete(camera)
    db.commit()
