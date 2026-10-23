/**
 * Display helpers for marketplace cards (pure): capability badges, report reasons and
 * error messages. Nothing here invents data — no ratings, no popularity numbers.
 */

import type { MarketplaceCapabilities, ReportReason } from "@/types/marketplace";

export interface CapabilityBadge {
  key: keyof MarketplaceCapabilities;
  label: string;
  icon: string;
}

const BADGES: readonly CapabilityBadge[] = [
  { key: "chat", label: "Chat", icon: "💬" },
  { key: "voice", label: "Voice", icon: "🔊" },
  { key: "realtime_voice", label: "Live voice", icon: "🎙️" },
  { key: "avatar", label: "Avatar", icon: "🎬" },
];

/** The capabilities a visitor can actually use, in a fixed order. */
export function capabilityBadges(capabilities: Partial<MarketplaceCapabilities> | null | undefined): CapabilityBadge[] {
  if (!capabilities) return [];
  return BADGES.filter((badge) => capabilities[badge.key] === true);
}

export const REPORT_REASONS: readonly { value: ReportReason; label: string }[] = [
  { value: "impersonation", label: "Impersonation (pretends to be someone it isn't)" },
  { value: "unauthorized_voice_or_avatar", label: "Uses a voice or face without permission" },
  { value: "privacy", label: "Privacy violation" },
  { value: "harmful_or_misleading", label: "Harmful or misleading content" },
  { value: "spam", label: "Spam" },
  { value: "other", label: "Other" },
];

export const MAX_REPORT_DESCRIPTION = 1000;
export const MAX_SHORT_DESCRIPTION = 200;

/** The text shown for a short description, falling back to the tagline. */
export function cardSummary(card: { short_description: string | null; tagline: string | null }): string | null {
  return card.short_description?.trim() || card.tagline?.trim() || null;
}

/** Error codes of the contract that are worth their own message. */
const CODE_MESSAGES: Record<string, string> = {
  discovery_off: "Discovery is turned off on this platform right now. Direct links to clones still work.",
  confirmation_required: "Please confirm that you want to publish this clone in the marketplace.",
  not_eligible: "This clone can't be listed yet: complete the requirements below first.",
  rate_limited: "Too many requests. Please wait a moment and try again.",
  not_found: "This clone isn't available in the marketplace.",
};

/** A code from `{code}` or `{detail: {code}}` error bodies, if present. */
export function errorCode(body: unknown): string | null {
  if (!body || typeof body !== "object") return null;
  const record = body as { code?: unknown; detail?: unknown };
  if (typeof record.code === "string") return record.code;
  if (record.detail && typeof record.detail === "object" && typeof (record.detail as { code?: unknown }).code === "string") {
    return (record.detail as { code: string }).code;
  }
  return null;
}

/**
 * A friendly message for a failed marketplace call: by code when known, else by HTTP
 * status, else the server's own (already user-safe) message.
 */
export function marketplaceErrorMessage(error: { status?: number; message?: string; code?: string | null } | null | undefined): string {
  if (!error) return "Something went wrong. Please try again.";
  if (error.code && CODE_MESSAGES[error.code]) return CODE_MESSAGES[error.code];
  switch (error.status) {
    case 401:
      return "Please log in to do that.";
    case 403:
      return error.message || CODE_MESSAGES.discovery_off;
    case 404:
      return CODE_MESSAGES.not_found;
    case 429:
      return CODE_MESSAGES.rate_limited;
    default:
      return error.message || "Something went wrong. Please try again.";
  }
}
