import { apiFetch } from "@/lib/api";
import type {
  ClonePermission,
  CloneShareRole,
  InvitationAccepted,
  Organization,
  OrganizationCreate,
  OrganizationUpdate,
  OrgClone,
  OrgInvitation,
  OrgInvitationCreated,
  OrgMember,
  OrgNotification,
  OrgRole,
  OrgUsage,
} from "@/types/organizations";

const enc = encodeURIComponent;
const org = (id: string) => `/api/organizations/${enc(id)}`;
const noStore: RequestInit = { cache: "no-store" };

/** Organizations (Phase 13). The API enforces every role rule; the UI only hides what won't work. */
export const orgApi = {
  list: () => apiFetch<Organization[]>("/api/organizations", noStore),
  get: (id: string) => apiFetch<Organization>(org(id), noStore),
  create: (payload: OrganizationCreate) =>
    apiFetch<Organization>("/api/organizations", { method: "POST", body: JSON.stringify(payload) }),
  update: (id: string, payload: OrganizationUpdate) =>
    apiFetch<Organization>(org(id), { method: "PATCH", body: JSON.stringify(payload) }),
  /** Owner only: deactivates the organization. */
  deactivate: (id: string) => apiFetch<{ ok: boolean }>(org(id), { method: "DELETE" }),
  leave: (id: string) => apiFetch<{ ok: boolean }>(`${org(id)}/leave`, { method: "POST" }),
  transferOwnership: (id: string, targetUserId: string) =>
    apiFetch<{ ok: boolean }>(`${org(id)}/transfer-ownership`, {
      method: "POST",
      body: JSON.stringify({ target_user_id: targetUserId, confirm: true }),
    }),

  members: (id: string) => apiFetch<OrgMember[]>(`${org(id)}/members`, noStore),
  changeRole: (id: string, memberId: string, role: Exclude<OrgRole, "owner">) =>
    apiFetch<OrgMember>(`${org(id)}/members/${enc(memberId)}`, { method: "PATCH", body: JSON.stringify({ role }) }),
  removeMember: (id: string, memberId: string) =>
    apiFetch<{ ok: boolean }>(`${org(id)}/members/${enc(memberId)}`, { method: "DELETE" }),

  invitations: (id: string) => apiFetch<OrgInvitation[]>(`${org(id)}/invitations`, noStore),
  invite: (id: string, email: string, role: Exclude<OrgRole, "owner">) =>
    apiFetch<OrgInvitationCreated>(`${org(id)}/invitations`, { method: "POST", body: JSON.stringify({ email, role }) }),
  cancelInvitation: (id: string, invitationId: string) =>
    apiFetch<{ ok: boolean }>(`${org(id)}/invitations/${enc(invitationId)}`, { method: "DELETE" }),
  acceptInvitation: (token: string) =>
    apiFetch<InvitationAccepted>(`/api/invitations/${enc(token)}/accept`, { method: "POST" }),
  declineInvitation: (token: string) =>
    apiFetch<{ ok: boolean }>(`/api/invitations/${enc(token)}/decline`, { method: "POST" }),

  clones: (id: string) => apiFetch<OrgClone[]>(`${org(id)}/clones`, noStore),
  assignClone: (id: string, cloneId: string) =>
    apiFetch<OrgClone>(`${org(id)}/clones/${enc(cloneId)}`, { method: "POST" }),
  unassignClone: (id: string, cloneId: string) =>
    apiFetch<{ ok: boolean }>(`${org(id)}/clones/${enc(cloneId)}`, { method: "DELETE" }),
  shareClone: (id: string, cloneId: string, userId: string, role: CloneShareRole) =>
    apiFetch<ClonePermission>(`${org(id)}/clones/${enc(cloneId)}/share?user_id=${enc(userId)}`, {
      method: "POST",
      body: JSON.stringify({ role }),
    }),
  unshareClone: (id: string, cloneId: string, userId: string) =>
    apiFetch<{ ok: boolean }>(`${org(id)}/clones/${enc(cloneId)}/share/${enc(userId)}`, { method: "DELETE" }),

  notifications: (id: string, limit = 5) =>
    apiFetch<OrgNotification[]>(`${org(id)}/notifications?limit=${limit}`, noStore),
  markAllRead: (id: string) => apiFetch<{ ok: boolean; count: number }>(`${org(id)}/notifications/read-all`, { method: "POST" }),
  usage: (id: string) => apiFetch<OrgUsage>(`${org(id)}/usage`, noStore),
};
