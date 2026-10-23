import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, false, text, true
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.avatar import AvatarVideoJob, CloneAvatar
    from app.models.conversation import Conversation
    from app.models.document import Document
    from app.models.memory import CloneMemory
    from app.models.public_chat import PublicChatSession
    from app.models.user import User

# Allowed values, shared with the API schemas and the migration.
RESPONSE_LENGTHS = ("short", "medium", "detailed")
VISIBILITIES = ("private", "public", "unlisted")
STATUSES = ("draft", "active", "disabled")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class CloneProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "clone_profiles"
    __table_args__ = (
        CheckConstraint(_in("response_length", RESPONSE_LENGTHS), name="ck_clone_profiles_response_length"),
        CheckConstraint(_in("visibility", VISIBILITIES), name="ck_clone_profiles_visibility"),
        CheckConstraint(_in("status", STATUSES), name="ck_clone_profiles_status"),
        CheckConstraint("NOT voice_enabled OR voice_consent_given", name="ck_clone_profiles_voice_consent"),
        CheckConstraint("NOT avatar_enabled OR avatar_consent_given", name="ck_clone_profiles_avatar_consent"),
        # Public listing filters on both.
        Index("ix_clone_profiles_visibility_status", "visibility", "status"),
        Index("ix_clone_profiles_status", "status"),
        # Phase 18 marketplace listing and sorting.
        Index(
            "ix_clone_profiles_marketplace",
            "marketplace_enabled",
            "marketplace_suspended",
            "visibility",
            "status",
        ),
        Index("ix_clone_profiles_marketplace_category", "marketplace_category"),
        Index("ix_clone_profiles_published_at", "published_at"),
        Index("ix_clone_profiles_featured_rank", "featured_rank"),
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    # URL-safe, unique across all clones (e.g. "ayaan-ai", "ayaan-ai-2").
    slug: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    tagline: Mapped[str | None] = mapped_column(String(160))
    bio: Mapped[str | None] = mapped_column(Text)
    profession: Mapped[str | None] = mapped_column(String(120))
    # A JSON list of strings; JSONB on PostgreSQL.
    skills: Mapped[list[str]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), default=list, server_default=text("'[]'")
    )
    preferred_language: Mapped[str | None] = mapped_column(String(60))
    communication_style: Mapped[str | None] = mapped_column(Text)
    personality_description: Mapped[str | None] = mapped_column(Text)
    response_length: Mapped[str] = mapped_column(String(10), default="medium", server_default="medium")
    visibility: Mapped[str] = mapped_column(String(10), default="private", server_default="private")
    avatar_url: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(10), default="active", server_default="active")
    # The owner must explicitly confirm they consent to a clone of themselves.
    owner_consent: Mapped[bool] = mapped_column(Boolean, default=False)

    # Voice. voice_enabled can only be true while voice_consent_given is true:
    # the owner confirmed permission to give this clone a voice. Voices are
    # AI-generated (a provider's prebuilt voice), never presented as the person's own.
    voice_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    voice_provider: Mapped[str | None] = mapped_column(String(40))
    voice_id: Mapped[str | None] = mapped_column(String(100))
    # "en" / "ur", or NULL to follow the language of each answer.
    voice_language: Mapped[str | None] = mapped_column(String(10))
    voice_consent_given: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    voice_consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Personal voice clone (ElevenLabs): made from the owner's own recordings, only with
    # explicit voice-clone consent. The recordings are not kept; the provider's voice id is.
    # Status: none, processing, ready, failed. use_cloned_voice: speak with it instead of a
    # prebuilt voice. Withdrawing consent deletes the voice at the provider.
    voice_clone_id: Mapped[str | None] = mapped_column(String(100))
    voice_clone_status: Mapped[str] = mapped_column(String(12), default="none", server_default="none")
    voice_clone_error: Mapped[str | None] = mapped_column(String(300))
    voice_clone_consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    use_cloned_voice: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())

    # Talking avatar. avatar_enabled needs avatar_consent_given (permission to use
    # this person's image) and an active avatar. Videos are labelled AI-generated.
    avatar_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    avatar_consent_given: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    avatar_consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Live video call (Simli): a "face" made from the active avatar photo. Reset when
    # the photo changes or consent is withdrawn. Status: none, processing, ready, failed.
    live_face_id: Mapped[str | None] = mapped_column(String(100))
    live_face_status: Mapped[str] = mapped_column(String(12), default="none", server_default="none")
    live_face_error: Mapped[str | None] = mapped_column(String(300))

    # Public access (/c/{slug}). Off until the owner turns it on; even then only
    # documents and memories marked public are used for visitors.
    public_chat_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    public_voice_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    public_avatar_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # Phase 16: the agent for visitors. Off by default; not offered publicly in this phase.
    public_agent_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # Phase 17: real-time voice conversations. The owner's switch (on), visitors (off by
    # default; also needs public chat + public voice) and how answers are spoken:
    # "voice" (the clone's voice, from the server) or "browser" (the browser's own voice).
    realtime_voice_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    public_realtime_voice_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    realtime_speech_mode: Mapped[str] = mapped_column(String(16), default="voice", server_default="voice")
    # Set when an administrator disables the clone: the owner can't turn it back on.
    admin_disabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())

    # Phase 18 marketplace. Off until the owner opts in (and the clone is public, active,
    # with public chat); an administrator can suspend it from the marketplace only.
    # featured_rank and the suspension reason are admin-only; the reason is never shown publicly.
    marketplace_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    marketplace_category: Mapped[str | None] = mapped_column(String(40))
    marketplace_tags: Mapped[list[str]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), default=list, server_default=text("'[]'")
    )
    short_description: Mapped[str | None] = mapped_column(String(200))
    featured_rank: Mapped[int | None] = mapped_column(Integer)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    marketplace_suspended: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    marketplace_suspended_reason: Mapped[str | None] = mapped_column(String(200))

    owner: Mapped["User"] = relationship(back_populates="clones")
    documents: Mapped[list["Document"]] = relationship(
        back_populates="clone", cascade="all, delete-orphan"
    )
    conversations: Mapped[list["Conversation"]] = relationship(
        back_populates="clone", cascade="all, delete-orphan"
    )
    memories: Mapped[list["CloneMemory"]] = relationship(back_populates="clone", cascade="all, delete-orphan")
    avatars: Mapped[list["CloneAvatar"]] = relationship(back_populates="clone", cascade="all, delete-orphan")
    avatar_jobs: Mapped[list["AvatarVideoJob"]] = relationship(cascade="all, delete-orphan")
    public_sessions: Mapped[list["PublicChatSession"]] = relationship(cascade="all, delete-orphan")
