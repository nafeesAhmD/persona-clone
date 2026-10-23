from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: Optional[str] = Field(default=None, max_length=500)
    slug: Optional[str] = Field(default=None, max_length=100)


class OrganizationUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=160)
    description: Optional[str] = Field(default=None, max_length=500)
    slug: Optional[str] = Field(default=None, max_length=100)
    avatar_url: Optional[str] = Field(default=None, max_length=500)
    is_active: Optional[bool] = None


class OrganizationRead(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    description: Optional[str]
    owner_id: uuid.UUID
    avatar_url: Optional[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class OrganizationMemberCreate(BaseModel):
    user_id: Optional[uuid.UUID] = None
    email: Optional[EmailStr] = None
    role: str = Field(default="viewer", pattern=r"^(owner|admin|editor|viewer)$")


class OrganizationMemberUpdate(BaseModel):
    # Ownership changes only through transfer-ownership.
    role: Optional[str] = Field(default=None, pattern=r"^(admin|editor|viewer)$")
    status: Optional[str] = Field(default=None, pattern=r"^(invited|active|suspended|removed)$")


class OrganizationMemberRead(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    user_id: uuid.UUID
    role: str
    status: str
    joined_at: datetime
    updated_at: datetime
    # Who the member is (filled in by the member list; other members of the organization see it).
    email: Optional[str] = None
    full_name: Optional[str] = None

    class Config:
        from_attributes = True


class OrganizationInvitationCreate(BaseModel):
    email: EmailStr
    # Nobody is invited as owner: ownership changes only through transfer-ownership.
    role: str = Field(default="viewer", pattern=r"^(admin|editor|viewer)$")


class OrganizationInvitationRead(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    email: EmailStr
    invited_by: uuid.UUID
    role: str
    status: str
    expires_at: datetime
    accepted_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


class OrganizationInvitationCreated(OrganizationInvitationRead):
    # The raw invitation token, shown only once (only its hash is stored). The invite
    # link is /api/invitations/{token}/accept; there is no e-mail delivery yet.
    token: str


class InvitationAccept(BaseModel):
    token: str


class InvitationDecline(BaseModel):
    token: str


class OwnershipTransfer(BaseModel):
    target_user_id: uuid.UUID
    confirm: bool = True


class CloneMemberPermissionUpdate(BaseModel):
    role: str = Field(pattern=r"^(owner|editor|viewer)$")


class CloneMemberPermissionRead(BaseModel):
    id: uuid.UUID
    clone_id: uuid.UUID
    user_id: uuid.UUID
    role: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class OrganizationCloneRead(BaseModel):
    id: uuid.UUID
    organization_id: Optional[uuid.UUID]
    owner_id: uuid.UUID
    name: str
    slug: str
    visibility: str
    status: str

    class Config:
        from_attributes = True
