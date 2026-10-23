"""Teams/Organizations models for Phase 13."""
import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin

_JSON = JSON().with_variant(JSONB(), "postgresql")

ORG_ROLES = ("owner", "admin", "editor", "viewer")
MEMBER_STATUSES = ("invited", "active", "suspended", "removed")
INVITE_STATUSES = ("pending", "accepted", "expired", "cancelled")


class Organization(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "organizations"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_organizations_slug"),
        Index("ix_organizations_owner_id", "owner_id"),
        Index("ix_organizations_is_active", "is_active"),
    )

    name: Mapped[str] = mapped_column(String(160))
    slug: Mapped[str] = mapped_column(String(100), index=True)  # unique via uq_organizations_slug
    description: Mapped[str | None] = mapped_column(String(500))
    owner_id: Mapped[uuid.UUID] = mapped_column()
    avatar_url: Mapped[str | None] = mapped_column(String(500))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class OrganizationMember(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "organization_members"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", name="uq_org_member_org_user"),
        Index("ix_org_member_org", "organization_id"),
        Index("ix_org_member_user", "user_id"),
        Index("ix_org_member_role", "role"),
        Index("ix_org_member_status", "status"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column()
    user_id: Mapped[uuid.UUID] = mapped_column()
    role: Mapped[str] = mapped_column(String(20), default="viewer")
    status: Mapped[str] = mapped_column(String(20), default="active")
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class OrganizationInvitation(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "organization_invitations"
    __table_args__ = (
        Index("ix_org_inv_org", "organization_id"),
        Index("ix_org_inv_email", "email"),
        Index("ix_org_inv_status", "status"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column()
    email: Mapped[str] = mapped_column(String(255))
    invited_by: Mapped[uuid.UUID] = mapped_column()
    role: Mapped[str] = mapped_column(String(20), default="viewer")
    token_hash: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CloneMemberPermission(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "clone_member_permissions"
    __table_args__ = (
        UniqueConstraint("clone_id", "user_id", name="uq_clone_perm_clone_user"),
        Index("ix_clone_perm_clone", "clone_id"),
        Index("ix_clone_perm_user", "user_id"),
    )

    clone_id: Mapped[uuid.UUID] = mapped_column()
    user_id: Mapped[uuid.UUID] = mapped_column()
    role: Mapped[str] = mapped_column(String(20), default="viewer")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class OrganizationSubscription(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "organization_subscriptions"
    __table_args__ = (
        Index("ix_org_sub_org", "organization_id"),
        Index("ix_org_sub_plan", "plan_id"),
        Index("ix_org_sub_status", "status"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column()
    plan_id: Mapped[uuid.UUID] = mapped_column()
    subscription_id: Mapped[uuid.UUID | None] = mapped_column()
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class OrganizationAuditLog(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "organization_audit_logs"
    __table_args__ = (
        Index("ix_org_audit_org", "organization_id"),
        Index("ix_org_audit_actor", "actor_user_id"),
        Index("ix_org_audit_action", "action"),
        Index("ix_org_audit_created", "created_at"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column()
    actor_user_id: Mapped[uuid.UUID] = mapped_column()
    action: Mapped[str] = mapped_column(String(60))
    target_type: Mapped[str] = mapped_column(String(40))
    target_id: Mapped[str | None] = mapped_column(String(64))
    metadata: Mapped[dict] = mapped_column(_JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
