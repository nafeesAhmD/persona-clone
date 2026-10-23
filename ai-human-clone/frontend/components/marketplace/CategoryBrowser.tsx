"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { ErrorBox } from "@/components/marketplace/MarketplaceCard";
import { CategoryChips } from "@/components/marketplace/MarketplaceHome";
import { marketplaceErrorMessage } from "@/lib/marketplace/display";
import { type MarketplaceError, marketplaceApi } from "@/lib/marketplaceApi";
import type { MarketplaceCategory } from "@/types/marketplace";

/** Every category with its live count of published clones (empty ones included). */
export function CategoryBrowser() {
  const [categories, setCategories] = useState<MarketplaceCategory[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    let cancelled = false;
    marketplaceApi
      .categories()
      .then((data) => {
        if (cancelled) return;
        setCategories(data);
        setError(null);
      })
      .catch((err: unknown) => !cancelled && setError(marketplaceErrorMessage(err as MarketplaceError)));
    return () => {
      cancelled = true;
    };
  }, [version]);

  return (
    <main className="mx-auto max-w-6xl px-4 py-6 sm:px-6 sm:py-12">
      <p className="text-sm text-muted">
        <Link href="/explore" className="hover:text-white">Explore</Link>
      </p>
      <h1 className="mt-1 text-2xl font-bold tracking-tight sm:text-3xl">Categories</h1>
      <p className="mt-2 text-muted">Owners choose a category when they publish their AI Clone.</p>
      <div className="mt-6">
        {error ? (
          <ErrorBox message={error} onRetry={() => setVersion((v) => v + 1)} />
        ) : !categories ? (
          <p className="text-sm text-muted" role="status">Loading categories…</p>
        ) : (
          <CategoryChips categories={categories} />
        )}
      </div>
    </main>
  );
}
