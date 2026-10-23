"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { inputClass } from "@/components/FormField";
import { CardGrid, CardSkeletons, EmptyBox, ErrorBox } from "@/components/marketplace/MarketplaceCard";
import { LoadMore, useMarketplaceList } from "@/components/marketplace/useMarketplaceList";
import { CATEGORIES, categoryIcon, categoryName } from "@/lib/marketplace/categories";
import { marketplaceErrorMessage } from "@/lib/marketplace/display";
import {
  EMPTY_FILTERS,
  MAX_FILTER_TAGS,
  MAX_QUERY_LENGTH,
  type MarketplaceFilters,
  filtersFromSearchParams,
  filtersToSearchParams,
  hasActiveFilters,
} from "@/lib/marketplace/filters";
import { type MarketplaceError, marketplaceApi } from "@/lib/marketplaceApi";
import type { MarketplaceCard, MarketplaceCategory, MarketplaceSort, MarketplaceTagCount } from "@/types/marketplace";

const PAGE_SIZE = 24;
const SECTION_SIZE = 6;

/**
 * The marketplace: search, filters (kept in the URL so a search can be shared), featured
 * and popular clones, categories and everything recently published. Real API data only:
 * no sample clones, no ratings.
 */
export function MarketplaceHome({ fixedCategory }: { fixedCategory?: string }) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const filters = useMemo<MarketplaceFilters>(() => {
    const parsed = filtersFromSearchParams(new URLSearchParams(searchParams.toString()));
    return fixedCategory ? { ...parsed, category: fixedCategory } : parsed;
  }, [searchParams, fixedCategory]);
  // On a category page the category itself isn't a "filter" the user chose.
  const filtering = hasActiveFilters(fixedCategory ? { ...filters, category: null } : filters);
  const browsing = !filtering && !filters.sort;

  // The search box updates the URL 350 ms after typing stops.
  const [draft, setDraft] = useState(filters.q);
  const [lastQ, setLastQ] = useState(filters.q);
  if (filters.q !== lastQ) {
    setLastQ(filters.q);
    setDraft(filters.q);
  }

  function update(next: Partial<MarketplaceFilters>) {
    const merged = { ...filters, ...next };
    const params = filtersToSearchParams(fixedCategory ? { ...merged, category: null } : merged);
    const text = params.toString();
    router.replace(text ? `${pathname}?${text}` : pathname, { scroll: false });
  }

  useEffect(() => {
    if (draft.trim() === filters.q) return;
    const timer = setTimeout(() => update({ q: draft.trim().slice(0, MAX_QUERY_LENGTH) }), 350);
    return () => clearTimeout(timer);
    // `update` reads the current filters; re-running on every render is not wanted.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft]);

  const listKey = filtersToSearchParams(filters).toString();
  const list = useMarketplaceList(
    (page) => (filters.q ? marketplaceApi.search(filters, page, PAGE_SIZE) : marketplaceApi.clones(filters, page, PAGE_SIZE)),
    listKey,
  );

  const title = fixedCategory ? categoryName(fixedCategory) ?? "Category" : "Explore AI Clones";

  return (
    <main className="mx-auto max-w-6xl px-4 py-6 sm:px-6 sm:py-12">
      {fixedCategory && (
        <p className="text-sm text-muted">
          <Link href="/explore" className="hover:text-white">Explore</Link>
          <span aria-hidden> / </span>
          <Link href="/explore/categories" className="hover:text-white">Categories</Link>
        </p>
      )}
      <h1 className="mt-1 text-2xl font-bold tracking-tight sm:text-3xl">
        {fixedCategory && <span aria-hidden>{categoryIcon(fixedCategory)} </span>}
        {title}
      </h1>
      <p className="mt-2 text-muted">
        AI representations that their owners chose to publish. Every answer is AI-generated — these are not the real people.
      </p>

      <form
        role="search"
        className="mt-6"
        onSubmit={(event) => {
          event.preventDefault();
          update({ q: draft.trim().slice(0, MAX_QUERY_LENGTH) });
        }}
      >
        <label className="sr-only" htmlFor="marketplace-search">Search AI Clones</label>
        <input
          id="marketplace-search"
          type="search"
          inputMode="search"
          enterKeyHint="search"
          autoComplete="off"
          maxLength={MAX_QUERY_LENGTH}
          placeholder="Search by name, profession, skill or tag…"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          className={inputClass}
        />
      </form>

      <Filters filters={filters} fixedCategory={fixedCategory} onChange={update} />

      {browsing && !fixedCategory ? (
        <BrowseSections />
      ) : null}

      <section className="mt-10" aria-labelledby="marketplace-results">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 id="marketplace-results" className="text-lg font-semibold">
            {filtering || filters.sort ? "Results" : fixedCategory ? "All in this category" : "Recently published"}
          </h2>
          {!list.loading && !list.error && (
            <p className="text-xs text-muted" aria-live="polite">
              {list.total} {list.total === 1 ? "AI Clone" : "AI Clones"}
            </p>
          )}
        </div>
        <div className="mt-4">
          <ResultList list={list} emptyText={filtering ? "No AI Clones match these filters." : "No AI Clones have been published here yet."} />
        </div>
      </section>
    </main>
  );
}

function ResultList({ list, emptyText }: { list: ReturnType<typeof useMarketplaceList>; emptyText: string }) {
  if (list.error && list.items.length === 0) return <ErrorBox message={list.error} onRetry={list.retry} />;
  if (list.loading && list.items.length === 0) return <CardSkeletons />;
  if (list.items.length === 0) return <EmptyBox>{emptyText}</EmptyBox>;
  return (
    <>
      <CardGrid clones={list.items} />
      {list.error && (
        <div className="mt-4">
          <ErrorBox message={list.error} onRetry={list.retry} />
        </div>
      )}
      <LoadMore list={list} />
    </>
  );
}

const SORT_LABELS: Record<MarketplaceSort, string> = {
  relevance: "Best match",
  newest: "Newest",
  popular: "Popular",
};

function Filters({
  filters,
  fixedCategory,
  onChange,
}: {
  filters: MarketplaceFilters;
  fixedCategory?: string;
  onChange: (next: Partial<MarketplaceFilters>) => void;
}) {
  const [tags, setTags] = useState<MarketplaceTagCount[]>([]);
  useEffect(() => {
    let cancelled = false;
    marketplaceApi
      .tags(20)
      .then((data) => !cancelled && setTags(data))
      .catch(() => undefined); // tags are optional extras
    return () => {
      cancelled = true;
    };
  }, []);

  const sorts: MarketplaceSort[] = filters.q ? ["relevance", "newest", "popular"] : ["newest", "popular"];
  const tagChoices = Array.from(new Set([...filters.tags, ...tags.map((t) => t.tag)])).slice(0, 20);

  return (
    <div className="mt-4 space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        {!fixedCategory && (
          <>
            <label className="sr-only" htmlFor="marketplace-category">Category</label>
            <select
              id="marketplace-category"
              value={filters.category ?? ""}
              onChange={(e) => onChange({ category: e.target.value || null })}
              className={`${inputClass} w-auto`}
            >
              <option value="">All categories</option>
              {CATEGORIES.map((c) => (
                <option key={c.slug} value={c.slug}>{c.name}</option>
              ))}
            </select>
          </>
        )}
        <label className="sr-only" htmlFor="marketplace-sort">Sort by</label>
        <select
          id="marketplace-sort"
          value={filters.sort && sorts.includes(filters.sort) ? filters.sort : sorts[0]}
          onChange={(e) => onChange({ sort: e.target.value as MarketplaceSort })}
          className={`${inputClass} w-auto`}
        >
          {sorts.map((s) => (
            <option key={s} value={s}>{SORT_LABELS[s]}</option>
          ))}
        </select>
        <Toggle label="🔊 Voice" checked={filters.voice} onChange={(voice) => onChange({ voice })} />
        <Toggle label="🎬 Avatar" checked={filters.avatar} onChange={(avatar) => onChange({ avatar })} />
        {(hasActiveFilters(fixedCategory ? { ...filters, category: null } : filters) || filters.sort) && (
          <button
            type="button"
            onClick={() => onChange({ ...EMPTY_FILTERS, category: fixedCategory ?? null })}
            className="min-h-11 rounded-xl px-3 text-muted hover:text-white"
          >
            Clear filters
          </button>
        )}
      </div>
      {tagChoices.length > 0 && (
        <div className="flex flex-wrap gap-2" role="group" aria-label="Filter by tag">
          {tagChoices.map((tag) => {
            const active = filters.tags.includes(tag);
            const full = !active && filters.tags.length >= MAX_FILTER_TAGS;
            return (
              <button
                key={tag}
                type="button"
                aria-pressed={active}
                disabled={full}
                onClick={() => onChange({ tags: active ? filters.tags.filter((t) => t !== tag) : [...filters.tags, tag] })}
                className={`min-h-9 rounded-full border px-3 text-xs ${active ? "border-accent bg-accent/15 text-accent-soft" : "border-border text-gray-300 hover:border-accent"} disabled:opacity-40`}
              >
                #{tag}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

function Toggle({ label, checked, onChange }: { label: string; checked: boolean; onChange: (checked: boolean) => void }) {
  return (
    <label className={`flex min-h-11 cursor-pointer items-center gap-2 rounded-xl border px-3 ${checked ? "border-accent bg-accent/10" : "border-border"}`}>
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} className="h-4 w-4 accent-accent" />
      {label}
    </label>
  );
}

/** Featured, categories and popular: shown when nothing is being searched or filtered. */
function BrowseSections() {
  const [featured, setFeatured] = useState<MarketplaceCard[] | null>(null);
  const [popular, setPopular] = useState<MarketplaceCard[] | null>(null);
  const [categories, setCategories] = useState<MarketplaceCategory[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const fail = (err: unknown) => !cancelled && setError(marketplaceErrorMessage(err as MarketplaceError));
    marketplaceApi.featured(SECTION_SIZE).then((d) => !cancelled && setFeatured(d)).catch(fail);
    marketplaceApi
      .clones({ ...EMPTY_FILTERS, sort: "popular" }, 1, SECTION_SIZE)
      .then((d) => !cancelled && setPopular(d.items))
      .catch(fail);
    marketplaceApi.categories().then((d) => !cancelled && setCategories(d)).catch(fail);
    return () => {
      cancelled = true;
    };
  }, [version]);

  if (error) {
    return (
      <div className="mt-8">
        <ErrorBox
          message={error}
          onRetry={() => {
            setError(null);
            setVersion((v) => v + 1);
          }}
        />
      </div>
    );
  }

  const used = (categories ?? []).filter((c) => c.count > 0).sort((a, b) => b.count - a.count).slice(0, 6);

  return (
    <>
      {featured && featured.length > 0 && (
        <Section title="Featured" id="featured">
          <CardGrid clones={featured} />
        </Section>
      )}
      <Section title="Categories" id="categories" more={{ href: "/explore/categories", label: "All categories" }}>
        {!categories ? (
          <div className="h-24 animate-pulse rounded-2xl border border-border bg-surface-raised/60" aria-hidden />
        ) : used.length === 0 ? (
          <EmptyBox>No AI Clones are published in any category yet.</EmptyBox>
        ) : (
          <CategoryChips categories={used} />
        )}
      </Section>
      {popular && popular.length > 0 && (
        <Section title="Popular" id="popular" note="Most saved and most chatted with in the last 30 days.">
          <CardGrid clones={popular} />
        </Section>
      )}
    </>
  );
}

export function CategoryChips({ categories }: { categories: MarketplaceCategory[] }) {
  return (
    <ul className="grid grid-cols-1 gap-3 min-[420px]:grid-cols-2 lg:grid-cols-3">
      {categories.map((c) => (
        <li key={c.slug}>
          <Link
            href={`/explore/${c.slug}`}
            className="flex min-h-14 items-center gap-3 rounded-2xl border border-border bg-surface-raised px-4 py-3 hover:border-accent"
          >
            <span className="text-xl" aria-hidden>{categoryIcon(c.slug)}</span>
            <span className="min-w-0 flex-1">
              <span className="block truncate font-medium">{c.name}</span>
              <span className="block text-xs text-muted">
                {c.count} {c.count === 1 ? "AI Clone" : "AI Clones"}
              </span>
            </span>
          </Link>
        </li>
      ))}
    </ul>
  );
}

function Section({
  title,
  id,
  note,
  more,
  children,
}: {
  title: string;
  id: string;
  note?: string;
  more?: { href: string; label: string };
  children: React.ReactNode;
}) {
  return (
    <section className="mt-10" aria-labelledby={`marketplace-${id}`}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id={`marketplace-${id}`} className="text-lg font-semibold">{title}</h2>
        {more && (
          <Link href={more.href} className="inline-flex min-h-11 items-center text-sm text-accent-soft hover:underline">
            {more.label}
          </Link>
        )}
      </div>
      {note && <p className="text-xs text-muted">{note}</p>}
      <div className="mt-4">{children}</div>
    </section>
  );
}
