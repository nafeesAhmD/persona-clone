/**
 * Marketplace API (Phase 18, docs/phase18/contract.md).
 *
 * Browsing works logged out; the session cookie is still sent so a logged-in user gets
 * `is_favorite`. Errors keep the server's `code` (e.g. "confirmation_required") so the
 * UI can react to it; messages are the server's user-safe text.
 */

import { API_URL, ApiError } from "@/lib/api";
import { errorCode } from "@/lib/marketplace/display";
import { type MarketplaceFilters, filtersToSearchParams } from "@/lib/marketplace/filters";
import { adminCloneParams, visibilityBody } from "@/lib/marketplace/admin";
import type {
  AdminMarketplaceClonePage,
  AdminMarketplaceCloneStatus,
  AdminMarketplaceVisibilityUpdate,
  AdminReportPage,
  FavoriteResult,
  MarketplaceAnalytics,
  MarketplaceCard,
  MarketplaceCategory,
  MarketplacePage,
  MarketplaceProfile,
  MarketplaceSettings,
  MarketplaceSettingsUpdate,
  MarketplaceTagCount,
  ReportCreated,
  ReportReason,
  ReportStatus,
} from "@/types/marketplace";

export class MarketplaceError extends ApiError {
  constructor(
    message: string,
    status: number | undefined,
    public readonly code: string | null,
  ) {
    super(message, status);
    this.name = "MarketplaceError";
  }
}

function messageOf(body: unknown, fallback: string): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && typeof (detail as { message?: unknown }).message === "string") {
    return (detail as { message: string }).message;
  }
  if (Array.isArray(detail) && detail[0] && typeof detail[0].msg === "string") return String(detail[0].msg);
  return fallback;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body) headers.set("Content-Type", "application/json");
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, { ...init, headers, credentials: "include", cache: "no-store" });
  } catch {
    throw new MarketplaceError("Could not reach the server. Check your connection and try again.", undefined, null);
  }
  if (!response.ok) {
    let body: unknown = null;
    try {
      body = await response.json();
    } catch {
      // Not JSON (e.g. a proxy error page).
    }
    throw new MarketplaceError(messageOf(body, `Request failed (${response.status})`), response.status, errorCode(body));
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

const enc = encodeURIComponent;
const send = <T,>(method: "POST" | "PATCH" | "DELETE", path: string, body?: unknown) =>
  request<T>(path, { method, body: body === undefined ? undefined : JSON.stringify(body) });

function withQuery(path: string, params: URLSearchParams): string {
  const text = params.toString();
  return text ? `${path}?${text}` : path;
}

export const marketplaceApi = {
  // --- Public ---
  clones: (filters: MarketplaceFilters, page = 1, pageSize?: number) =>
    request<MarketplacePage>(withQuery("/api/marketplace/clones", filtersToSearchParams(filters, { page, pageSize }))),
  search: (filters: MarketplaceFilters, page = 1, pageSize?: number) =>
    request<MarketplacePage>(withQuery("/api/marketplace/search", filtersToSearchParams(filters, { page, pageSize }))),
  featured: (limit = 8) => request<MarketplaceCard[]>(`/api/marketplace/clones/featured?limit=${limit}`),
  categories: () => request<MarketplaceCategory[]>("/api/marketplace/categories"),
  tags: (limit = 30) => request<MarketplaceTagCount[]>(`/api/marketplace/tags?limit=${limit}`),
  profile: (slug: string) => request<MarketplaceProfile>(`/api/marketplace/clones/${enc(slug)}`),
  report: (slug: string, reason: ReportReason, description?: string) =>
    send<ReportCreated>("POST", `/api/marketplace/clones/${enc(slug)}/report`, {
      reason,
      ...(description?.trim() ? { description: description.trim() } : {}),
    }),

  // --- Favorites (login required) ---
  favorites: (page = 1, pageSize = 24) =>
    request<MarketplacePage>(`/api/marketplace/favorites?page=${page}&page_size=${pageSize}`),
  addFavorite: (cloneId: string) => send<FavoriteResult>("POST", `/api/marketplace/favorites/${enc(cloneId)}`),
  removeFavorite: (cloneId: string) => send<void>("DELETE", `/api/marketplace/favorites/${enc(cloneId)}`),

  // --- Owner ---
  settings: (cloneId: string) => request<MarketplaceSettings>(`/api/clones/${enc(cloneId)}/marketplace`),
  updateSettings: (cloneId: string, update: MarketplaceSettingsUpdate) =>
    send<MarketplaceSettings>("PATCH", `/api/clones/${enc(cloneId)}/marketplace`, update),
  analytics: (cloneId: string, days = 30) =>
    request<MarketplaceAnalytics>(`/api/clones/${enc(cloneId)}/marketplace/analytics?days=${days}`),

  // --- Admin ---
  adminReports: (query: { status?: ReportStatus | ""; page?: number; page_size?: number }) => {
    const params = new URLSearchParams();
    if (query.status) params.set("status", query.status);
    params.set("page", String(query.page ?? 1));
    params.set("page_size", String(query.page_size ?? 20));
    return request<AdminReportPage>(withQuery("/api/admin/marketplace/reports", params));
  },
  adminUpdateReport: (reportId: string, status: ReportStatus, resolutionNote?: string) =>
    send<unknown>("PATCH", `/api/admin/marketplace/reports/${enc(reportId)}`, {
      status,
      ...(resolutionNote?.trim() ? { resolution_note: resolutionNote.trim() } : {}),
    }),
  adminClones: (query: { status?: AdminMarketplaceCloneStatus; q?: string; page?: number; page_size?: number }) =>
    request<AdminMarketplaceClonePage>(withQuery("/api/admin/marketplace/clones", adminCloneParams(query))),
  /** Sends only the given fields: the server changes nothing else. */
  adminSetVisibility: (cloneId: string, update: AdminMarketplaceVisibilityUpdate) =>
    send<unknown>("PATCH", `/api/admin/marketplace/clones/${enc(cloneId)}/visibility`, visibilityBody(update)),
};
