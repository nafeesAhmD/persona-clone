// Organization role rules for the UI (no React, no DOM): tested in tests/org.test.ts.
// They mirror backend/app/org/routes/*: the server still checks every action.
import type { Organization, OrgInvitation, OrgMember, OrgRole } from "@/types/organizations";

export const ROLE_RANK: Record<OrgRole, number> = { viewer: 1, editor: 2, admin: 3, owner: 4 };

export const ROLE_LABELS: Record<OrgRole, string> = {
  owner: "Owner",
  admin: "Admin",
  editor: "Editor",
  viewer: "Viewer",
};

export const ROLE_DESCRIPTIONS: Record<OrgRole, string> = {
  owner: "Full control, including ownership and deactivation.",
  admin: "Manages members, invitations, clones and settings.",
  editor: "Works on the organization's clones.",
  viewer: "Can view the organization's clones.",
};

export type AssignableRole = Exclude<OrgRole, "owner">;

/** The signed-in user's role: the organization's owner, else their active membership's role. */
export function myRole(org: Pick<Organization, "owner_id">, members: OrgMember[], userId: string | undefined): OrgRole | null {
  if (!userId) return null;
  if (org.owner_id === userId) return "owner";
  const mine = members.find((m) => m.user_id === userId && m.status === "active");
  return mine ? mine.role : null;
}

export function isManager(role: OrgRole | null): boolean {
  return role === "owner" || role === "admin";
}

/** Roles the actor may give (in invitations and role changes). Owner only through transfer. */
export function assignableRoles(actor: OrgRole | null): AssignableRole[] {
  if (actor === "owner") return ["admin", "editor", "viewer"];
  if (actor === "admin") return ["editor", "viewer"];
  return [];
}

/** May the actor change this member's role or remove them? (Owner: anyone but the owner; admin: editors/viewers.) */
export function canManageMember(actor: OrgRole | null, target: Pick<OrgMember, "role" | "user_id">, org: Pick<Organization, "owner_id">): boolean {
  if (target.role === "owner" || target.user_id === org.owner_id) return false;
  if (actor === "owner") return true;
  if (actor === "admin") return target.role !== "admin";
  return false;
}

export const canInvite = isManager;
export const canEditSettings = isManager;
export const canAssignClones = isManager;
export const canShareClones = isManager;

export function canTransferOwnership(role: OrgRole | null): boolean {
  return role === "owner";
}

export const canDeactivate = canTransferOwnership;

/** Owners can't leave: they transfer ownership first. */
export function canLeave(role: OrgRole | null): boolean {
  return role !== null && role !== "owner";
}

/** A clone's owner, or an organization owner/admin, can take it out of the organization. */
export function canUnassignClone(role: OrgRole | null, clone: { owner_id: string }, userId: string | undefined): boolean {
  return isManager(role) || (!!userId && clone.owner_id === userId);
}

/** Active members, the owner first, then by rank, then by name. */
export function sortMembers(members: OrgMember[]): OrgMember[] {
  return members
    .filter((m) => m.status === "active")
    .sort((a, b) => ROLE_RANK[b.role] - ROLE_RANK[a.role] || displayName(a).localeCompare(displayName(b)));
}

export function displayName(member: Pick<OrgMember, "full_name" | "email" | "user_id">): string {
  return member.full_name?.trim() || member.email || `Member ${member.user_id.slice(0, 8)}`;
}

/** Up to two initials for an avatar circle. */
export function initials(member: Pick<OrgMember, "full_name" | "email" | "user_id">): string {
  const name = displayName(member).replace(/@.*/, "");
  const parts = name.split(/[\s._-]+/).filter(Boolean);
  return ((parts[0]?.[0] ?? "?") + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase();
}

/** Invitations still waiting for an answer (and not past their expiry). */
export function pendingInvitations(invitations: OrgInvitation[], now: Date = new Date()): OrgInvitation[] {
  return invitations.filter((i) => i.status === "pending" && new Date(i.expires_at).getTime() > now.getTime());
}

/** The link someone opens to accept: /invite/{token} on this site. */
export function inviteLink(origin: string, token: string): string {
  return `${origin.replace(/\/+$/, "")}/invite/${encodeURIComponent(token)}`;
}

const ERROR_MESSAGES: Record<string, string> = {
  already_member: "That person is already a member of this organization.",
  duplicate_pending: "There's already a pending invitation for that email address.",
  invalid_or_expired: "This invitation has expired, was cancelled, or was already used.",
  invitation_for_another_email: "This invitation was sent to a different email address than the one you're signed in with.",
  owner_cannot_leave_transfer_first: "Owners can't leave. Transfer ownership to another member first.",
  cannot_modify_owner: "The owner's role can only change through an ownership transfer.",
  cannot_remove_owner: "The owner can't be removed.",
  slug_taken: "That short name is already taken.",
  clone_in_another_organization: "That clone already belongs to another organization.",
  clone_not_found: "That clone wasn't found (you can only add clones you own).",
  org_clone_limit_reached: "This organization has reached its clone limit.",
  organization_inactive: "This organization is deactivated.",
  target_not_active_member: "That person isn't an active member.",
  already_owner: "You already own this organization.",
  confirm_required: "Please confirm first.",
  invalid_clone: "That clone isn't part of this organization.",
  not_member: "You're not a member of this organization.",
  forbidden: "You don't have permission to do that.",
  not_found: "This organization doesn't exist or was removed.",
};

/** A friendly sentence for the API's short error codes; other messages pass through. */
export function orgErrorMessage(error: unknown, fallback = "Something went wrong. Please try again."): string {
  const message = error instanceof Error ? error.message : typeof error === "string" ? error : "";
  if (!message) return fallback;
  return ERROR_MESSAGES[message.trim()] ?? message;
}
