"use client";

import { useEffect, useRef, useState } from "react";

import { marketplaceErrorMessage } from "@/lib/marketplace/display";
import type { MarketplaceError } from "@/lib/marketplaceApi";
import type { MarketplaceCard, MarketplacePage } from "@/types/marketplace";

interface Loaded {
  /** Which request (filters + retry count) this data answers. */
  wanted: string;
  items: MarketplaceCard[];
  total: number;
  page: number;
  error: string | null;
}

/**
 * A paged marketplace list with "Load more": page 1 is fetched again whenever `key`
 * changes (new filters); later pages are appended without duplicates. Answers to
 * older filters are ignored.
 */
export function useMarketplaceList(load: (page: number) => Promise<MarketplacePage>, key: string) {
  const [version, setVersion] = useState(0);
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [more, setMore] = useState<{ wanted: string; loading: boolean; error: string | null } | null>(null);
  const loadRef = useRef(load);
  const wanted = `${key}#${version}`;
  const wantedRef = useRef(wanted);

  useEffect(() => {
    loadRef.current = load;
    wantedRef.current = wanted;
  });

  useEffect(() => {
    let cancelled = false;
    loadRef
      .current(1)
      .then((data) => !cancelled && setLoaded({ wanted, items: data.items, total: data.total, page: 1, error: null }))
      .catch(
        (err: unknown) =>
          !cancelled &&
          setLoaded({ wanted, items: [], total: 0, page: 1, error: marketplaceErrorMessage(err as MarketplaceError) }),
      );
    return () => {
      cancelled = true;
    };
  }, [wanted]);

  const current = loaded?.wanted === wanted ? loaded : null;
  const moreState = more?.wanted === wanted ? more : null;

  function loadMore() {
    if (!current || moreState?.loading) return;
    const target = current.page + 1;
    const forRequest = wanted;
    setMore({ wanted: forRequest, loading: true, error: null });
    loadRef
      .current(target)
      .then((data) => {
        if (wantedRef.current !== forRequest) return;
        setLoaded((prev) => {
          if (!prev || prev.wanted !== forRequest) return prev;
          const seen = new Set(prev.items.map((c) => c.id));
          return { ...prev, items: [...prev.items, ...data.items.filter((c) => !seen.has(c.id))], total: data.total, page: target };
        });
        setMore({ wanted: forRequest, loading: false, error: null });
      })
      .catch((err: unknown) => {
        if (wantedRef.current === forRequest) {
          setMore({ wanted: forRequest, loading: false, error: marketplaceErrorMessage(err as MarketplaceError) });
        }
      });
  }

  const items = current?.items ?? [];
  return {
    items,
    total: current?.total ?? 0,
    loading: !current || Boolean(moreState?.loading),
    error: current?.error ?? moreState?.error ?? null,
    hasMore: Boolean(current) && items.length < (current?.total ?? 0),
    loadMore,
    retry: () => (current && current.items.length > 0 ? loadMore() : setVersion((v) => v + 1)),
  };
}

export function LoadMore({ list, label = "Load more" }: { list: ReturnType<typeof useMarketplaceList>; label?: string }) {
  if (!list.hasMore || list.items.length === 0) return null;
  return (
    <div className="mt-6 flex flex-col items-center gap-2">
      <button
        type="button"
        onClick={list.loadMore}
        disabled={list.loading}
        aria-busy={list.loading}
        className="min-h-11 rounded-xl border border-border px-6 text-sm hover:border-accent disabled:opacity-50"
      >
        {list.loading ? "Loading…" : label}
      </button>
      <p className="text-xs text-muted" aria-live="polite">
        Showing {list.items.length} of {list.total}
      </p>
    </div>
  );
}
