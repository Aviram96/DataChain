"""Tests for attaching registered camera streams (Slice B / CP-B.P5)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.camera import Camera
from app.models.user import User
from app.security.password import hash_password
from app.services.camera_stream import (
    CameraNotFoundForStream,
    attach_camera_stream,
    get_active_camera,
)

import app.models as _models  # noqa: F401


@pytest.fixture
def db_session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


def test_attach_active_camera_stream(db_session: Session) -> None:
    user = User(email="stream@example.com", password_hash=hash_password("password12"))
    db_session.add(user)
    db_session.flush()
    camera = Camera(
        user_id=user.id,
        name="Front",
        stream_url="rtsp://192.0.2.50/live",
    )
    db_session.add(camera)
    db_session.commit()

    assert attach_camera_stream(db_session, camera.id) == "rtsp://192.0.2.50/live"
    assert get_active_camera(db_session, camera.id).name == "Front"


def test_attach_soft_deleted_camera_raises(db_session: Session) -> None:
    from datetime import datetime, timezone

    user = User(email="gone@example.com", password_hash=hash_password("password12"))
    db_session.add(user)
    db_session.flush()
    camera = Camera(
        user_id=user.id,
        name="Gone",
        stream_url="http://192.0.2.51/live",
        deleted_at=datetime.now(timezone.utc),
    )
    db_session.add(camera)
    db_session.commit()

    with pytest.raises(CameraNotFoundForStream):
        attach_camera_stream(db_session, camera.id)

    with pytest.raises(CameraNotFoundForStream):
        attach_camera_stream(db_session, uuid4())
