"""Video-record (segment) API schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class VideoRecordPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    camera_id: UUID
    started_at: datetime
    ended_at: datetime
    ipfs_cid: str
    segment_hash: str
    tx_hash: str | None


class VideoRecordListResponse(BaseModel):
    items: list[VideoRecordPublic]
    total: int
    page: int
    page_size: int
    pages: int
