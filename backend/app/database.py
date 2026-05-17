"""Database configuration and SQLAlchemy base for backend services."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.orm import DeclarativeBase

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def get_database_url() -> str:
    """Return database URL from env with a local Postgres default."""
    return os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://datachain:datachain_dev@localhost:5432/datachain",
    )


class Base(DeclarativeBase):
    """Base class for SQLAlchemy declarative models."""
