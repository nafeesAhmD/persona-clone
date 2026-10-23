/**
 * Marketplace filters ↔ query strings (pure; tested in tests/marketplace.test.ts).
 *
 * The same filters drive the page URL (so a search can be shared and survives a reload)
 * and the API query. Anything invalid is dropped rather than sent: the server would
 * reject it with a 400 anyway (docs/phase18/contract.md).
 */

import type { MarketplaceSort } from "@/types/marketplace";

import { isCategory } from "./categories.ts";

export const MAX_QUERY_LENGTH = 100;
export const MAX_FILTER_TAGS = 5;
export const MAX_TAGS_PER_CLONE = 8;
export const DEFAULT_PAGE_SIZE = 24;
export const MAX_PAGE_SIZE = 48;
const SORTS: readonly MarketplaceSort[] = ["relevance", "newest", "popular"];

/** Tag rule of the contract: 2–30 characters of a-z 0-9 space + # . - (lowercase). */
const TAG_PATTERN = /^[a-z0-9 +#.-]{2,30}$/;

export function normalizeTag(value: string): string {
  return value.trim().toLowerCase().replace(/\s+/g, " ");
}

export function isValidTag(value: string): boolean {
  const tag = normalizeTag(value);
  return TAG_PATTERN.test(tag) && tag.trim() === tag;
}

/** "Python, data  science,python" -> ["python", "data science"] (valid, unique, in order). */
export function parseTags(input: string | null | undefined, max = MAX_FILTER_TAGS): string[] {
  if (!input) return [];
  const seen: string[] = [];
  for (const part of input.split(",")) {
    const tag = normalizeTag(part);
    if (tag && isValidTag(tag) && !seen.includes(tag)) seen.push(tag);
    if (seen.length >= max) break;
  }
  return seen;
}

export interface MarketplaceFilters {
  q: string;
  category: string | null;
  tags: string[];
  profession: string;
  voice: boolean;
  avatar: boolean;
  /** null = the server's default (relevance with a query, newest without). */
  sort: MarketplaceSort | null;
}

export const EMPTY_FILTERS: MarketplaceFilters = {
  q: "",
  category: null,
  tags: [],
  profession: "",
  voice: false,
  avatar: false,
  sort: null,
};

function cleanText(value: string | null | undefined): string {
  return (value ?? "").trim().slice(0, MAX_QUERY_LENGTH);
}

function isSort(value: unknown): value is MarketplaceSort {
  return typeof value === "string" && (SORTS as readonly string[]).includes(value);
}

/** Page URL (or any query string) -> filters. Unknown or invalid values are ignored. */
export function filtersFromSearchParams(params: URLSearchParams): MarketplaceFilters {
  const category = params.get("category");
  const sort = params.get("sort");
  return {
    q: cleanText(params.get("q")),
    category: isCategory(category) ? category : null,
    tags: parseTags(params.get("tags")),
    profession: cleanText(params.get("profession")),
    voice: params.get("voice_enabled") === "true",
    avatar: params.get("avatar_enabled") === "true",
    sort: isSort(sort) ? sort : null,
  };
}

/** Filters -> query string (the page URL and the API use the same names). */
export function filtersToSearchParams(
  filters: MarketplaceFilters,
  paging?: { page?: number; pageSize?: number },
): URLSearchParams {
  const params = new URLSearchParams();
  const q = cleanText(filters.q);
  if (q) params.set("q", q);
  if (filters.category && isCategory(filters.category)) params.set("category", filters.category);
  const tags = parseTags(filters.tags.join(","));
  if (tags.length) params.set("tags", tags.join(","));
  const profession = cleanText(filters.profession);
  if (profession) params.set("profession", profession);
  if (filters.voice) params.set("voice_enabled", "true");
  if (filters.avatar) params.set("avatar_enabled", "true");
  // "relevance" needs a query: without one the server would sort by newest anyway.
  if (filters.sort && isSort(filters.sort) && !(filters.sort === "relevance" && !q)) params.set("sort", filters.sort);
  if (paging?.page !== undefined) params.set("page", String(Math.max(1, Math.floor(paging.page))));
  if (paging?.pageSize !== undefined) {
    params.set("page_size", String(Math.min(MAX_PAGE_SIZE, Math.max(1, Math.floor(paging.pageSize)))));
  }
  return params;
}

export function hasActiveFilters(filters: MarketplaceFilters): boolean {
  return Boolean(
    cleanText(filters.q) ||
      filters.category ||
      filters.tags.length ||
      cleanText(filters.profession) ||
      filters.voice ||
      filters.avatar,
  );
}

export function sameFilters(a: MarketplaceFilters, b: MarketplaceFilters): boolean {
  return filtersToSearchParams(a).toString() === filtersToSearchParams(b).toString();
}
