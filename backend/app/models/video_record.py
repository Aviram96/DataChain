"""One-minute segment metadata (Slice D / CP-D.P6).

Rows are written after IPFS (and, when successful, chain) in a later slice.
``tx_hash`` is nullable so a CID can be stored before an on-chain proof exists
(CP-D.P7). ``segment_hash`` is the SHA-256 hex from the ingest integrity check.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.camera import Camera


class VideoRecord(Base):
    __tablename__ = "video_records"
    __table_args__ = (
        sa.UniqueConstraint(
            "camera_id",
            "started_at",
            name="uq_video_records_camera_id_started_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    camera_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("cameras.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    started_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, index=True
    )
    ended_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    ipfs_cid: Mapped[str] = mapped_column(sa.String(255), nullable=False, index=True)
    segment_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    tx_hash: Mapped[str | None] = mapped_column(
        sa.String(66), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )

    camera: Mapped["Camera"] = relationship(back_populates="video_records")
