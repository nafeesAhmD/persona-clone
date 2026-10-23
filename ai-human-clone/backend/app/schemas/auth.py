import re
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

USERNAME_PATTERN = re.compile(r"^[a-z0-9_]{3,30}$")
PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128


def validate_password_strength(password: str) -> str:
    if len(password) < PASSWORD_MIN_LENGTH:
        raise ValueError(f"must be at least {PASSWORD_MIN_LENGTH} characters")
    if len(password) > PASSWORD_MAX_LENGTH:
        raise ValueError(f"must be at most {PASSWORD_MAX_LENGTH} characters")
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        raise ValueError("must contain at least one letter and one number")
    return password


def normalize_username(username: str) -> str:
    username = username.strip().lower()
    if not USERNAME_PATTERN.fullmatch(username):
        raise ValueError("must be 3-30 characters: lowercase letters, numbers and underscores")
    return username


def _clean_full_name(value: str | None) -> str | None:
    if value is None:
        return None
    value = " ".join(value.split())
    return value or None


class RegisterRequest(BaseModel):
    # Unknown fields (e.g. "is_admin") are rejected, never silently stored.
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    username: str
    full_name: str | None = Field(default=None, max_length=255)
    password: str

    @field_validator("email")
    @classmethod
    def lower_email(cls, value: str) -> str:
        return value.lower()

    @field_validator("username")
    @classmethod
    def check_username(cls, value: str) -> str:
        return normalize_username(value)

    @field_validator("password")
    @classmethod
    def check_password(cls, value: str) -> str:
        return validate_password_strength(value)

    @field_validator("full_name")
    @classmethod
    def check_full_name(cls, value: str | None) -> str | None:
        return _clean_full_name(value)


class LoginRequest(BaseModel):
    email: EmailStr
    # No strength rules here: only check that something was sent.
    password: str = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)

    @field_validator("email")
    @classmethod
    def lower_email(cls, value: str) -> str:
        return value.lower()


class UserUpdate(BaseModel):
    """Fields a user may change on their own account. Anything else is rejected."""

    model_config = ConfigDict(extra="forbid")

    full_name: str | None = Field(default=None, max_length=255)
    username: str | None = None

    @field_validator("username")
    @classmethod
    def check_username(cls, value: str | None) -> str | None:
        return None if value is None else normalize_username(value)

    @field_validator("full_name")
    @classmethod
    def check_full_name(cls, value: str | None) -> str | None:
        return _clean_full_name(value)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)
    new_password: str

    @field_validator("new_password")
    @classmethod
    def check_new_password(cls, value: str) -> str:
        return validate_password_strength(value)


class UserRead(BaseModel):
    """Safe public view of a user. hashed_password is deliberately absent."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    username: str
    full_name: str | None
    is_active: bool
    # Read-only: shown so the app can offer the admin area; it can't be set through the API.
    is_admin: bool = False
    created_at: datetime
