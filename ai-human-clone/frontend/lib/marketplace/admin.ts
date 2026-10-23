/**
 * Admin marketplace request helpers (pure; tested in tests/marketplace.test.ts).
 * The visibility PATCH changes only the fields it receives, so nothing is sent "just in case".
 */

import type { AdminMarketplaceCloneStatus, AdminMarketplaceVisibilityUpdate } from "@/types/marketplace";

const STATUSES: readonly AdminMarketplaceCloneStatus[] = ["listed", "suspended", "featured", "all"];
export const MAX_FEATURED_RANK = 1000;
export const MAX_SUSPEND_REASON = 200;

export function adminCloneParams(query: {
  status?: AdminMarketplaceCloneStatus;
  q?: string;
  page?: number;
  page_size?: number;
}): URLSearchParams {
  const params = new URLSearchParams();
  if (query.status && STATUSES.includes(query.status)) params.set("status", query.status);
  const q = (query.q ?? "").trim().slice(0, 100);
  if (q) params.set("q", q);
  params.set("page", String(Math.max(1, Math.floor(query.page ?? 1))));
  params.set("page_size", String(Math.min(100, Math.max(1, Math.floor(query.page_size ?? 20)))));
  return params;
}

/** The PATCH body: only defined fields; a blank reason is left out; rank null = "not featured". */
export function visibilityBody(update: AdminMarketplaceVisibilityUpdate): AdminMarketplaceVisibilityUpdate {
  const body: AdminMarketplaceVisibilityUpdate = {};
  if (update.suspended !== undefined) body.suspended = update.suspended;
  const reason = update.reason?.trim().slice(0, MAX_SUSPEND_REASON);
  if (update.suspended === true && reason) body.reason = reason;
  if (update.featured_rank !== undefined) body.featured_rank = update.featured_rank;
  return body;
}

/** "" -> null (clear); a whole number 0–1000 -> that number; anything else -> undefined (invalid). */
export function parseFeaturedRank(text: string): number | null | undefined {
  const value = text.trim();
  if (value === "") return null;
  if (!/^\d+$/.test(value)) return undefined;
  const rank = Number(value);
  return rank <= MAX_FEATURED_RANK ? rank : undefined;
}
