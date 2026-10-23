"use client";

import Link from "next/link";
import { useState } from "react";

import { FavoriteButton } from "@/components/marketplace/FavoriteButton";
import { CardGrid, CardSkeletons, EmptyBox, ErrorBox } from "@/components/marketplace/MarketplaceCard";
import { LoadMore, useMarketplaceList } from "@/components/marketplace/useMarketplaceList";
import { marketplaceApi } from "@/lib/marketplaceApi";

const PAGE_SIZE = 24;

/**
 * The user's saved clones. Clones that are no longer listed (made private, removed from
 * the marketplace, suspended) are hidden by the server; they come back if relisted.
 */
export function SavedClones() {
  const list = useMarketplaceList((page) => marketplaceApi.favorites(page, PAGE_SIZE), "favorites");
  const [removed, setRemoved] = useState<Set<string>>(new Set());
  const items = list.items.filter((c) => !removed.has(c.id));

  return (
    <main className="mx-auto max-w-6xl px-4 py-6 sm:px-6 sm:py-12">
      <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">Saved AI Clones</h1>
      <p className="mt-2 text-muted">
        Clones you saved from the marketplace. Only clones that are still published are shown.
      </p>
      <div className="mt-8">
        {list.error && list.items.length === 0 ? (
          <ErrorBox message={list.error} onRetry={list.retry} />
        ) : list.loading && list.items.length === 0 ? (
          <CardSkeletons count={3} />
        ) : items.length === 0 ? (
          <EmptyBox>
            You haven&apos;t saved any AI Clones yet.{" "}
            <Link href="/explore" className="text-accent-soft hover:underline">Explore the marketplace</Link>
          </EmptyBox>
        ) : (
          <>
            <CardGrid
              clones={items}
              action={(clone) => (
                <FavoriteButton
                  compact
                  cloneId={clone.id}
                  cloneName={clone.name}
                  initial
                  onChange={(saved) => !saved && setRemoved((prev) => new Set(prev).add(clone.id))}
                />
              )}
            />
            <LoadMore list={list} />
          </>
        )}
      </div>
    </main>
  );
}
