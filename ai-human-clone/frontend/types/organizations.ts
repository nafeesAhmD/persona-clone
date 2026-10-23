export type OrgRole = "owner" | "admin" | "editor" | "viewer";

export interface Organization {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  owner_id: string;
  avatar_url: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface OrganizationCreate {
  name: string;
  description?: string | null;
}

export interface OrganizationUpdate {
  name?: string;
  description?: string | null;
}

export interface OrgMember {
  id: string;
  organization_id: string;
  user_id: string;
  role: OrgRole;
  /** invited | active | suspended | removed */
  status: string;
  joined_at: string;
  updated_at: string;
  email: string | null;
  full_name: string | null;
}

export interface OrgInvitation {
  id: string;
  organization_id: string;
  email: string;
  invited_by: string;
  role: OrgRole;
  /** pending | accepted | cancelled | expired */
  status: string;
  expires_at: string;
  accepted_at: string | null;
  created_at: string;
}

/** The reply to creating an invitation: the raw token is shown this one time only. */
export interface OrgInvitationCreated extends OrgInvitation {
  token: string;
}

export interface OrgClone {
  id: string;
  organization_id: string | null;
  owner_id: string;
  name: string;
  slug: string;
  visibility: string;
  status: string;
}

export type CloneShareRole = "owner" | "editor" | "viewer";

export interface ClonePermission {
  id: string;
  clone_id: string;
  user_id: string;
  role: CloneShareRole;
  created_at: string;
  updated_at: string;
}

export interface OrgNotification {
  id: string;
  type: string;
  title: string;
  message: string;
  is_read: boolean;
  created_at: string;
}

export interface UsedLimit {
  used: number;
  limit: number | null;
}

export interface OrgUsage {
  plan_name: string;
  plan_slug: string;
  members: UsedLimit;
  clones: UsedLimit;
  messages: UsedLimit;
  documents: UsedLimit;
}

export interface InvitationAccepted {
  ok: boolean;
  organization_id: string;
  role: OrgRole;
}
