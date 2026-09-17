"""Verification-attempt API schemas (Slice E / CP-E.P8)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

VerifyScope = Literal["full", "partial", "minute"]
VerifyStatus = Literal["verified", "tampered", "missing", "failed_to_verify"]

MAX_ATTEMPT_MINUTES = 24 * 60


class VerificationMinuteCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    started_at: datetime
    status: VerifyStatus
    detail: str = Field(min_length=1, max_length=500)
    video_record_id: UUID | None = None


class VerificationAttemptCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    started_at: datetime
    ended_at: datetime
    scope: VerifyScope
    overall_status: VerifyStatus
    minutes: list[VerificationMinuteCreate] = Field(
        min_length=1, max_length=MAX_ATTEMPT_MINUTES
    )


class VerificationMinutePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    started_at: datetime
    status: VerifyStatus
    detail: str
    video_record_id: UUID | None


class VerificationAttemptSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    camera_id: UUID
    started_at: datetime
    ended_at: datetime
    scope: VerifyScope
    overall_status: VerifyStatus
    created_at: datetime


class VerificationAttemptPublic(VerificationAttemptSummary):
    minutes: list[VerificationMinutePublic]


class VerificationAttemptListResponse(BaseModel):
    items: list[VerificationAttemptSummary]
    total: int
    page: int
    page_size: int
    pages: int
