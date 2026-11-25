"""Video-record (segment) API schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

PlaybackStatus = Literal[
    "verified",
    "tampered",
    "missing",
    "unavailable",
    "failed",
]


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


class PlaybackSegmentPublic(BaseModel):
    """One segment result. No local file path."""

    video_record_id: UUID
    started_at: datetime
    ended_at: datetime
    status: PlaybackStatus
    detail: str


class PlaybackIntervalPublic(BaseModel):
    started_at: datetime
    ended_at: datetime
    detail: str


class PlaybackExcludedPublic(PlaybackIntervalPublic):
    status: PlaybackStatus
    video_record_id: UUID


class PlaybackDenial(BaseModel):
    """Returned when Watch must not receive media."""

    overall: PlaybackStatus
    detail: str
    segments: list[PlaybackSegmentPublic]
    missing_intervals: list[PlaybackIntervalPublic]
    excluded_intervals: list[PlaybackExcludedPublic]


class DownloadSegmentPublic(PlaybackSegmentPublic):
    """One download segment result. Includes the chain transaction when known."""

    tx_hash: str | None = None


class DownloadVerificationReport(BaseModel):
    """Per-segment download verification. No local file paths."""

    overall: PlaybackStatus
    detail: str
    discontinuous: bool
    segments: list[DownloadSegmentPublic]
    missing_intervals: list[PlaybackIntervalPublic]
    excluded_intervals: list[PlaybackExcludedPublic]
