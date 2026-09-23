"""Auth schemas — registration, login, and token responses."""

import datetime
import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserOut(BaseModel):
    """Public user representation (never exposes the password hash)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    created_at: datetime.datetime


class RegisterRequest(BaseModel):
    """Body of POST /auth/register."""

    email: EmailStr
    password: str = Field(
        min_length=8,
        max_length=128,
        description="Plaintext password; stored only as a hash.",
    )


class LoginRequest(BaseModel):
    """Body of POST /auth/login."""

    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    """Body shared by /auth/register and /auth/login."""

    access_token: str
    token_type: str = "bearer"
    user: UserOut
