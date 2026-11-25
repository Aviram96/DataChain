"""Auth-related API schemas."""

from __future__ import annotations

import re
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

# Printable ASCII except space: letters, numbers, and special characters.
_ALLOWED_PASSWORD = re.compile(r"^[!-~]+$")


class UserRegister(BaseModel):
    email: EmailStr
    password: str

    @field_validator("email", mode="before")
    @classmethod
    def strip_email(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("password")
    @classmethod
    def password_policy(cls, value: str) -> str:
        if len(value) < 8:
            raise ValueError("Password must be at least 8 characters.")
        if len(value) > 64:
            raise ValueError("Password must be at most 64 characters.")
        if _ALLOWED_PASSWORD.fullmatch(value) is None:
            raise ValueError(
                "Password can contain only English letters, numbers, "
                "and special characters."
            )
        return value


class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    created_at: datetime


class UserLogin(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
