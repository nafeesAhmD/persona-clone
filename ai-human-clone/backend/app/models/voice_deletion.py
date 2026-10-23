"""Cloned voices whose delete at the provider has not fully succeeded yet."""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin


class PendingVoiceDeletion(UUIDPrimaryKeyMixin, Base):
    """A voice the owner removed (or withdrew consent for) that is still stored at a
    provider, e.g. on a Colab GPU service that was off. Retried hourly until gone."""

    __tablename__ = "pending_voice_deletions"

    # "<provider>:<voice id>", as stored in clone_profiles.voice_clone_id.
    voice_clone_id: Mapped[str] = mapped_column(String(100), unique=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
