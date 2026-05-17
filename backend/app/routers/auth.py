"""Authentication routes (registration, login, JWT)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.deps import get_db
from app.deps_auth import get_current_user
from app.models.user import User
from app.schemas.auth import TokenResponse, UserLogin, UserPublic, UserRegister
from app.security.jwt_tokens import create_access_token
from app.security.password import hash_password, verify_password

router = APIRouter()


@router.post(
    "/register",
    response_model=UserPublic,
    status_code=status.HTTP_201_CREATED,
)
def register(payload: UserRegister, db: Session = Depends(get_db)) -> User:
    email_norm = str(payload.email).lower()
    existing = db.execute(
        select(User.id).where(User.email == email_norm)
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )

    user = User(
        email=email_norm,
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        ) from None
    db.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
def login(payload: UserLogin, db: Session = Depends(get_db)) -> TokenResponse:
    email_norm = str(payload.email).lower()
    user = db.execute(select(User).where(User.email == email_norm)).scalar_one_or_none()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
        )
    token = create_access_token(str(user.id))
    return TokenResponse(access_token=token, token_type="bearer")


@router.get("/me", response_model=UserPublic)
def read_me(current_user: User = Depends(get_current_user)) -> User:
    """Return the authenticated user (requires ``Authorization: Bearer <token>``)."""
    return current_user
