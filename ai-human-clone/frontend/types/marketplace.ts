/** Marketplace & discovery (Phase 18). Shapes follow docs/phase18/contract.md. */

export type MarketplaceSort = "relevance" | "newest" | "popular";

export interface MarketplaceCategoryRef {
  slug: string;
  name: string;
}

export interface MarketplaceCapabilities {
  chat: boolean;
  voice: boolean;
  avatar: boolean;
  realtime_voice: boolean;
}

/** A clone in discovery results. Public metadata only (no owner details, no ratings). */
export interface MarketplaceCard {
  id: string;
  slug: string;
  name: string;
  profession: string | null;
  short_description: string | null;
  tagline: string | null;
  /** An API path served without login, or an owner-provided URL. */
  avatar_url: string | null;
  category: MarketplaceCategoryRef | null;
  tags: string[];
  skills: string[];
  capabilities: MarketplaceCapabilities;
  published_at: string | null;
  featured: boolean;
}

export interface MarketplaceProfile extends MarketplaceCard {
  bio: string | null;
  preferred_language: string | null;
  favorites: number;
  /** Only meaningful when logged in; false otherwise. */
  is_favorite: boolean;
  public_url: string;
}

export interface MarketplacePage {
  items: MarketplaceCard[];
  total: number;
  page: number;
  page_size: number;
  sort: MarketplaceSort;
}

export interface MarketplaceCategory {
  slug: string;
  name: string;
  description: string;
  count: number;
}

export interface MarketplaceTagCount {
  tag: string;
  count: number;
}

export interface FavoriteResult {
  clone_id: string;
  created_at: string;
}

export type ReportReason =
  | "impersonation"
  | "unauthorized_voice_or_avatar"
  | "privacy"
  | "harmful_or_misleading"
  | "spam"
  | "other";

export interface ReportCreated {
  id: string;
  status: ReportStatus;
}

export type ReportStatus = "open" | "reviewing" | "resolved" | "dismissed";

// --- Owner -------------------------------------------------------------------------

export interface MarketplaceRequirement {
  key: string;
  ok: boolean;
  label: string;
}

export interface MarketplaceSettings {
  enabled: boolean;
  category: string | null;
  tags: string[];
  short_description: string | null;
  published_at: string | null;
  suspended: boolean;
  eligible: boolean;
  listed: boolean;
  requirements: MarketplaceRequirement[];
  preview: MarketplaceCard;
  public_url: string;
}

export interface MarketplaceSettingsUpdate {
  enabled?: boolean;
  category?: string | null;
  tags?: string[];
  short_description?: string | null;
  confirm_publish?: boolean;
}

export interface MarketplaceDailyPoint {
  date: string;
  views: number;
  favorites: number;
}

export interface MarketplaceAnalytics {
  views: number;
  favorites: number;
  public_chat_starts: number;
  daily: MarketplaceDailyPoint[];
}

// --- Admin -------------------------------------------------------------------------

export interface AdminReportRow {
  id: string;
  clone: { id: string; name: string; slug: string };
  /** The reporter's email (admins only), or "anonymous". */
  reporter: string;
  reason: ReportReason;
  description: string | null;
  status: ReportStatus;
  created_at: string;
  reviewed_at: string | null;
  resolution_note: string | null;
}

export interface AdminReportPage {
  items: AdminReportRow[];
  total: number;
  page: number;
  page_size: number;
}

/** Only the fields sent are changed (e.g. a featured rank alone keeps a suspension). */
export interface AdminMarketplaceVisibilityUpdate {
  suspended?: boolean;
  reason?: string;
  featured_rank?: number | null;
}

export type AdminMarketplaceCloneStatus = "listed" | "suspended" | "featured" | "all";

export interface AdminMarketplaceClone {
  id: string;
  name: string;
  slug: string;
  marketplace_enabled: boolean;
  listed: boolean;
  suspended: boolean;
  suspended_reason: string | null;
  featured_rank: number | null;
  published_at: string | null;
  open_reports: number;
}

export interface AdminMarketplaceClonePage {
  items: AdminMarketplaceClone[];
  total: number;
  page: number;
  page_size: number;
}
