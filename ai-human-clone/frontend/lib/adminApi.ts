import { apiFetch } from "@/lib/api";
import type {
  AdminCloneDetail,
  AdminCloneRow,
  AdminUserDetail,
  AdminUserRow,
  AuditLogRow,
  DashboardStats,
  ErrorEventRow,
  Page,
  PlatformSettings,
  PlatformSettingsUpdate,
  PlatformStatus,
  PublicCloneItem,
  PublicDocumentItem,
  PublicMemoryItem,
  SecurityEventRow,
  SystemHealth,
  UsageReport,
} from "@/types/admin";

/**
 * Admin API calls. Every one of these is checked by the server (require_admin);
 * the admin pages being hidden from other users is only for convenience.
 */

type Query = Record<string, string | number | boolean | null | undefined>;

function withQuery(path: string, query?: Query): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
  }
  const text = params.toString();
  return text ? `${path}?${text}` : path;
}

const get = <T,>(path: string, query?: Query) => apiFetch<T>(withQuery(path, query), { cache: "no-store" });
const send = <T,>(method: "POST" | "PATCH", path: string, body: unknown = {}) =>
  apiFetch<T>(path, { method, body: JSON.stringify(body) });
const id = encodeURIComponent;

export const adminApi = {
  dashboard: () => get<DashboardStats>("/api/admin/dashboard"),

  users: (query: Query) => get<Page<AdminUserRow>>("/api/admin/users", query),
  user: (userId: string) => get<AdminUserDetail>(`/api/admin/users/${id(userId)}`),
  setUserActive: (userId: string, isActive: boolean, reason?: string) =>
    send<AdminUserDetail>("PATCH", `/api/admin/users/${id(userId)}/status`, { is_active: isActive, reason }),

  clones: (query: Query) => get<Page<AdminCloneRow>>("/api/admin/clones", query),
  clone: (cloneId: string) => get<AdminCloneDetail>(`/api/admin/clones/${id(cloneId)}`),
  setCloneStatus: (cloneId: string, status: "active" | "disabled", reason?: string) =>
    send<AdminCloneDetail>("PATCH", `/api/admin/clones/${id(cloneId)}/status`, { status, reason }),

  publicClones: (query: Query) => get<Page<PublicCloneItem>>("/api/admin/content/public-clones", query),
  publicDocuments: (query: Query) => get<Page<PublicDocumentItem>>("/api/admin/content/public-documents", query),
  publicMemories: (query: Query) => get<Page<PublicMemoryItem>>("/api/admin/content/public-memories", query),
  makeClonePrivate: (cloneId: string, reason?: string) =>
    send<void>("POST", `/api/admin/content/clones/${id(cloneId)}/make-private`, { reason }),
  disablePublicClone: (cloneId: string, reason?: string) =>
    send<AdminCloneDetail>("POST", `/api/admin/content/clones/${id(cloneId)}/disable`, { reason }),
  makeDocumentPrivate: (documentId: string, reason?: string) =>
    send<void>("POST", `/api/admin/content/documents/${id(documentId)}/make-private`, { reason }),
  makeMemoryPrivate: (memoryId: string, reason?: string) =>
    send<void>("POST", `/api/admin/content/memories/${id(memoryId)}/make-private`, { reason }),

  securityEvents: (query: Query) => get<Page<SecurityEventRow>>("/api/admin/security/events", query),
  auditLogs: (query: Query) => get<Page<AuditLogRow>>("/api/admin/audit-logs", query),
  usage: (days: number) => get<UsageReport>("/api/admin/usage", { days }),
  systemHealth: () => get<SystemHealth>("/api/admin/system/health"),
  errors: (query: Query) => get<Page<ErrorEventRow>>("/api/admin/system/errors", query),

  settings: () => get<PlatformSettings>("/api/admin/settings"),
  updateSettings: (changes: PlatformSettingsUpdate) => send<PlatformSettings>("PATCH", "/api/admin/settings", changes),
};

export function getPlatformStatus(): Promise<PlatformStatus> {
  return apiFetch<PlatformStatus>("/api/platform/status", { cache: "no-store" });
}
