"use client";

import Link from "next/link";
import { useState } from "react";

import { Segmented } from "@/components/analytics/RangeSelector";
import { EmptyState, LoadingBlock, PageShell, btnPrimary, useApiData } from "@/components/analytics/ui";
import { ApiErrorState } from "@/components/ApiErrorState";
import { getMyClones } from "@/lib/api";
import { analyticsApi } from "@/lib/analyticsApi";
import { RANGE_OPTIONS, rangeLabel } from "@/lib/analyticsChart";
import { formatCompact } from "@/lib/usage";
import type { AnalyticsOverview, AnalyticsRange } from "@/types/analytics";
import type { CloneSummary } from "@/types/clone";

type Row = { clone: CloneSummary; overview: AnalyticsOverview | null };

/** Overview of every clone you own; one request per clone, failures shown per card. */
async function loadRows(range: AnalyticsRange): Promise<Row[]> {
  const clones = await getMyClones();
  const overviews = await Promise.allSettled(clones.map((c) => analyticsApi.overview(c.id, range)));
  return clones.map((clone, i) => {
    const result = overviews[i];
    return { clone, overview: result.status === "fulfilled" ? result.value : null };
  });
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="min-w-0">
      <dt className="truncate text-xs text-muted">{label}</dt>
      <dd className="text-lg font-semibold text-white">{formatCompact(value)}</dd>
    </div>
  );
}

export function AnalyticsHub() {
  const [range, setRange] = useState<AnalyticsRange>("7d");
  const { data, error, loading, reload } = useApiData(() => loadRows(range), range);

  return (
    <PageShell title="Analytics" description="How your clones are being used. Counts only, never conversation content.">
      <div className="space-y-4">
        <Segmented
          legend="Period"
          options={RANGE_OPTIONS.map((o) => ({ value: o.value, label: o.short }))}
          value={range}
          onChange={setRange}
        />
        {error && !data ? (
          <ApiErrorState error={error} thing="analytics" onRetry={reload} />
        ) : !data ? (
          <LoadingBlock label="Loading analytics…" />
        ) : data.length === 0 ? (
          <EmptyState title="No clones yet" body="Create a clone to start seeing analytics here.">
            <Link href="/create-clone" className={btnPrimary}>
              Create a clone
            </Link>
          </EmptyState>
        ) : (
          <ul className={`grid gap-3 sm:grid-cols-2 ${loading ? "opacity-60" : ""}`} aria-busy={loading}>
            {data.map(({ clone, overview }) => (
              <li key={clone.id}>
                <Link
                  href={`/clone/${encodeURIComponent(clone.id)}/analytics`}
                  className="block rounded-2xl border border-border bg-surface-raised/60 p-4 hover:border-accent focus-visible:border-accent"
                  aria-label={`${clone.name}: open analytics`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <h2 className="min-w-0 truncate font-semibold text-white">{clone.name}</h2>
                    <span className="shrink-0 text-sm text-accent-soft" aria-hidden="true">
                      Details →
                    </span>
                  </div>
                  <p className="mt-0.5 text-xs text-muted">{rangeLabel(range)}</p>
                  {overview ? (
                    <dl className="mt-3 grid grid-cols-3 gap-2">
                      <Metric label="Messages" value={overview.total_messages} />
                      <Metric label="Convs" value={overview.total_conversations} />
                      <Metric label="Visitors" value={overview.total_public_sessions} />
                    </dl>
                  ) : (
                    <p className="mt-3 text-sm text-amber-300">Couldn&apos;t load numbers for this clone.</p>
                  )}
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </PageShell>
  );
}
