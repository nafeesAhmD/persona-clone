from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Integer, String, false, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.clone_profile import CloneProfile


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    # Stored lower-cased so uniqueness is case-insensitive.
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    username: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    full_name: Mapped[str | None] = mapped_column(String(255))
    # Argon2 hash. Never returned by the API.
    hashed_password: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true(), index=True)
    # Platform administrator. Never settable through the API: only the server-side CLI
    # (python -m app.cli) or INITIAL_ADMIN_EMAIL can grant it.
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # Temporary protection against password guessing (see auth_service.authenticate).
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Sessions (access tokens) issued before this moment are refused; set when the
    # password changes so other devices are signed out (see deps.session_user).
    sessions_valid_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    clones: Mapped[list["CloneProfile"]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )
