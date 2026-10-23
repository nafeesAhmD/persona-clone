"use client";

import { useEffect, useState } from "react";

import { useAuth } from "@/components/AuthProvider";
import { marketplaceApi } from "@/lib/marketplaceApi";
import type { MarketplaceProfile } from "@/types/marketplace";

/**
 * The marketplace view of a public clone page: null while loading or when the clone
 * isn't listed (unlisted, opted out, suspended, discovery off) — the page then shows
 * only what it always did. Re-fetched after login so `is_favorite` is right.
 */
export function useMarketplaceProfile(slug: string): { profile: MarketplaceProfile | null; checked: boolean } {
  const { status } = useAuth();
  const [state, setState] = useState<{ key: string; profile: MarketplaceProfile | null } | null>(null);
  const key = `${slug}:${status}`;

  useEffect(() => {
    if (status === "loading") return;
    let cancelled = false;
    marketplaceApi
      .profile(slug)
      .then((profile) => !cancelled && setState({ key, profile }))
      .catch(() => !cancelled && setState({ key, profile: null }));
    return () => {
      cancelled = true;
    };
  }, [slug, status, key]);

  const current = state?.key === key ? state : null;
  return { profile: current?.profile ?? null, checked: current !== null };
}
