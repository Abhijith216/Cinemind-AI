"""Auth endpoints (JWT): register + login."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db_session
from app.core.security import create_access_token, create_password_hash, verify_password
from app.models import User
from app.schemas.auth import (
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserOut,
)

logger = logging.getLogger("app.api.auth")

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(
    payload: RegisterRequest,
    db: AsyncSession = Depends(get_db_session),
) -> TokenResponse:
    """Create an account and return a JWT for it immediately."""
    existing = await db.execute(select(User).where(User.email == payload.email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="email already registered")

    user = User(
        email=payload.email,
        hashed_password=create_password_hash(payload.password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    logger.info("registered user %s", user.email)
    return TokenResponse(
        access_token=create_access_token(user.id),
        user=UserOut.model_validate(user),
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    db: AsyncSession = Depends(get_db_session),
) -> TokenResponse:
    """Verify credentials and return a fresh JWT (401 on any mismatch)."""
    found = await db.execute(select(User).where(User.email == payload.email))
    found_user = found.scalar_one_or_none()
    if found_user is None or not verify_password(
        payload.password, found_user.hashed_password
    ):
        raise HTTPException(status_code=401, detail="invalid email or password")
    return TokenResponse(
        access_token=create_access_token(found_user.id),
        user=UserOut.model_validate(found_user),
    )
