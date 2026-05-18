"""Camera API schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CameraBase(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=200)
    stream_url: str = Field(min_length=1, max_length=2000)
    location: str | None = Field(default=None, max_length=200)

    @field_validator("stream_url")
    @classmethod
    def stream_url_must_be_http_or_rtsp(cls, value: str) -> str:
        lowered = value.lower()
        if not (
            lowered.startswith("http://")
            or lowered.startswith("https://")
            or lowered.startswith("rtsp://")
        ):
            raise ValueError(
                "Stream URL must start with http://, https://, or rtsp://"
            )
        return value


class CameraCreate(CameraBase):
    pass


class CameraUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=200)
    stream_url: str | None = Field(default=None, min_length=1, max_length=2000)
    location: str | None = Field(default=None, max_length=200)

    @field_validator("stream_url")
    @classmethod
    def stream_url_must_be_http_or_rtsp(cls, value: str | None) -> str | None:
        if value is None:
            return value
        lowered = value.lower()
        if not (
            lowered.startswith("http://")
            or lowered.startswith("https://")
            or lowered.startswith("rtsp://")
        ):
            raise ValueError(
                "Stream URL must start with http://, https://, or rtsp://"
            )
        return value


class CameraPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    stream_url: str
    location: str | None
    created_at: datetime


class CameraListResponse(BaseModel):
    items: list[CameraPublic]
    total: int
    page: int
    page_size: int
    pages: int
