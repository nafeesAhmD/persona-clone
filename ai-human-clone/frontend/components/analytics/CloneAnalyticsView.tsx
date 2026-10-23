"use client";

import Link from "next/link";
import { useState } from "react";

import { AgentAnalyticsSection } from "@/components/agent/AgentAnalyticsSection";
import { ActivityChart } from "@/components/analytics/ActivityChart";
import { Segmented } from "@/components/analytics/RangeSelector";
import { Collapsible, EmptyState, LoadingBlock, PageShell, btnSecondary, useApiData } from "@/components/analytics/ui";
import { ApiErrorState } from "@/components/ApiErrorState";
import { getClone } from "@/lib/api";
import { analyticsApi } from "@/lib/analyticsApi";
import { RANGE_OPTIONS, errorRate, formatDuration, rangeLabel, totals } from "@/lib/analyticsChart";
import { formatCompact, formatNumber } from "@/lib/usage";
import type { AnalyticsOverview, AnalyticsRange } from "@/types/analytics";

export function SummaryCard({
  label,
  value,
  hint,
  tone,
  className = "",
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: "bad";
  className?: string;
}) {
  return (
    <div className={`min-w-0 rounded-2xl border border-border bg-surface-raised/60 p-3 sm:p-4 ${className}`}>
      <p className="truncate text-xs uppercase tracking-wide text-muted">{label}</p>
      <p className={`mt-1 text-2xl font-semibold ${tone === "bad" ? "text-rose-300" : "text-white"}`}>{value}</p>
      {hint && <p className="mt-0.5 text-xs text-muted">{hint}</p>}
    </div>
  );
}

function SummaryCards({ overview }: { overview: AnalyticsOverview }) {
  const rate = errorRate(overview.successful_requests, overview.failed_requests);
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
      <SummaryCard label="Messages" value={formatCompact(overview.total_messages)} hint={formatNumber(overview.total_messages)} />
      <SummaryCard label="Conversations" value={formatCompact(overview.total_conversations)} hint="started" />
      <SummaryCard label="Visitors" value={formatCompact(overview.total_public_sessions)} hint="public chat sessions" />
      <SummaryCard
        label="Knowledge"
        value={formatCompact(overview.total_documents)}
        hint={`documents · ${formatNumber(overview.total_memories)} memories`}
      />
      <SummaryCard
        label="Errors"
        value={formatCompact(overview.failed_requests)}
        hint={rate === null ? "failed requests" : `${rate}% of requests failed`}
        tone={overview.failed_requests > 0 ? "bad" : undefined}
        className="col-span-2 sm:col-span-1"
      />
    </div>
  );
}

function Details({ overview }: { overview: AnalyticsOverview }) {
  const rows: [string, string][] = [
    ["Voice requests", formatNumber(overview.total_voice_requests)],
    ["Avatar videos", formatNumber(overview.total_avatar_requests)],
    ["Successful requests", formatNumber(overview.successful_requests)],
    ["Failed requests", formatNumber(overview.failed_requests)],
    ["Average response time", formatDuration(overview.average_response_time)],
    ["Unique sessions", formatNumber(overview.total_unique_sessions)],
    ["Usage events", formatNumber(overview.total_usage_events)],
  ];
  return (
    <dl className="divide-y divide-border text-sm">
      {rows.map(([label, value]) => (
        <div key={label} className="flex items-center justify-between gap-3 py-2">
          <dt className="text-muted">{label}</dt>
          <dd className="font-medium text-white">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

export function CloneAnalyticsView({ cloneId }: { cloneId: string }) {
  const [range, setRange] = useState<AnalyticsRange>("7d");
  const clone = useApiData(() => getClone(cloneId), cloneId);
  const overview = useApiData(() => analyticsApi.overview(cloneId, range), `${cloneId}:${range}`);
  const activity = useApiData(() => analyticsApi.activity(cloneId, range), `${cloneId}:${range}`);

  if (clone.error && !clone.data) return <ApiErrorState error={clone.error} thing="clone" onRetry={clone.reload} />;

  const title = clone.data ? `${clone.data.name} analytics` : "Clone analytics";
  const activityTotals = activity.data ? totals(activity.data.days) : null;

  return (
    <PageShell
      title={title}
      description="Counts only — conversation content is never shown here."
      back={{ href: `/clone/${encodeURIComponent(cloneId)}`, label: "Back to clone" }}
    >
      <div className="space-y-4">
        <Segmented
          legend="Period"
          options={RANGE_OPTIONS.map((o) => ({ value: o.value, label: o.short }))}
          value={range}
          onChange={setRange}
        />
        <p className="sr-only" aria-live="polite">
          {overview.loading ? `Loading ${rangeLabel(range)}` : `Showing ${rangeLabel(range)}`}
        </p>

        {overview.error && !overview.data ? (
          <ApiErrorState error={overview.error} thing="analytics" onRetry={overview.reload} />
        ) : !overview.data ? (
          <LoadingBlock label="Loading analytics…" />
        ) : (
          <div className={overview.loading ? "opacity-60 transition-opacity" : ""}>
            <SummaryCards overview={overview.data} />
          </div>
        )}

        <Collapsible
          title="Activity per day"
          meta={activityTotals ? `${formatNumber(activityTotals.messages)} messages` : undefined}
        >
          {activity.error && !activity.data ? (
            <ApiErrorState error={activity.error} thing="activity" onRetry={activity.reload} />
          ) : !activity.data ? (
            <LoadingBlock label="Loading activity…" />
          ) : activity.data.days.every((d) => !d.messages && !d.conversations && !d.sessions && !d.errors) ? (
            <EmptyState title="No activity yet" body={`Nothing happened in ${rangeLabel(range).toLowerCase()}. Share your clone or chat with it to see activity here.`}>
              <Link href={`/clone/${encodeURIComponent(cloneId)}/chat`} className={btnSecondary}>
                Open chat
              </Link>
            </EmptyState>
          ) : (
            <ActivityChart days={activity.data.days} />
          )}
        </Collapsible>

        <Collapsible title="AI agent" defaultOpen={false}>
          <AgentAnalyticsSection cloneId={cloneId} range={range} />
        </Collapsible>

        {overview.data && (
          <Collapsible title="More details" defaultOpen={false}>
            <Details overview={overview.data} />
          </Collapsible>
        )}
      </div>
    </PageShell>
  );
}
