"""FastAPI dependencies."""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy.orm import Session

from app.db.session import get_sessionmaker

SessionLocal = get_sessionmaker()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
