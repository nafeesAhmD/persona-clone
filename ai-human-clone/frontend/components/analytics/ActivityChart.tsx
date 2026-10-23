"use client";

import { useState } from "react";

import { Segmented } from "@/components/analytics/RangeSelector";
import { METRIC_LABELS, barHeights, describeChart, formatDay, labelEvery, totals } from "@/lib/analyticsChart";
import { formatNumber } from "@/lib/usage";
import type { ActivityMetric, DailyActivity } from "@/types/analytics";

const METRICS: ActivityMetric[] = ["messages", "conversations", "sessions", "errors"];

/**
 * Daily bars in plain CSS (no chart library). Scrolls sideways inside its own box on
 * small screens; a text summary and a data table give the same information without the picture.
 */
export function ActivityChart({ days }: { days: DailyActivity[] }) {
  const [metric, setMetric] = useState<ActivityMetric>("messages");
  const values = days.map((d) => d[metric]);
  const { max, heights } = barHeights(values);
  const every = labelEvery(days.length);
  const sum = totals(days)[metric];
  const summary = describeChart(days, metric);
  const barColor = metric === "errors" ? "bg-rose-400/80" : "bg-accent/80";

  return (
    <div className="space-y-3">
      <Segmented
        legend="Metric shown in the chart"
        options={METRICS.map((m) => ({ value: m, label: METRIC_LABELS[m] }))}
        value={metric}
        onChange={setMetric}
        wrap
      />
      <p className="text-sm text-gray-200">
        <span className="font-semibold text-white">{formatNumber(sum)}</span> {METRIC_LABELS[metric].toLowerCase()} in this period
      </p>

      <div
        className="overflow-x-auto overscroll-x-contain rounded-xl border border-border bg-surface p-3"
        tabIndex={0}
        role="region"
        aria-label={`${METRIC_LABELS[metric]} per day chart (scrolls sideways)`}
      >
        <div role="img" aria-label={summary} style={{ minWidth: `${Math.max(days.length * 14, 240)}px` }}>
          <div className="mb-1 flex justify-between text-[11px] text-muted" aria-hidden="true">
            <span>{formatNumber(max)}</span>
            <span>per day</span>
          </div>
          <div className="relative flex h-36 items-end gap-[3px] border-b border-l border-border/80" aria-hidden="true">
            <div className="pointer-events-none absolute inset-x-0 top-1/2 border-t border-dashed border-border/60" />
            {days.map((d, i) => (
              <div key={d.date} className="flex h-full min-w-[8px] flex-1 items-end" title={`${formatDay(d.date)}: ${d[metric]}`}>
                <div className={`w-full rounded-t ${barColor}`} style={{ height: `${heights[i]}%` }} />
              </div>
            ))}
          </div>
          <div className="mt-1 flex gap-[3px] text-[10px] text-muted" aria-hidden="true">
            {days.map((d, i) => (
              <div key={d.date} className="min-w-[8px] flex-1 overflow-visible whitespace-nowrap">
                {i % every === 0 ? formatDay(d.date) : ""}
              </div>
            ))}
          </div>
        </div>
      </div>
      <p className="text-xs text-muted">{summary}</p>

      <details className="rounded-xl border border-border">
        <summary className="flex min-h-11 cursor-pointer items-center px-3 text-sm text-accent-soft">Show data as a table</summary>
        <div className="max-h-72 overflow-auto">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">Activity per day</caption>
            <thead className="sticky top-0 bg-surface-raised text-xs text-muted">
              <tr>
                <th scope="col" className="px-3 py-2 font-medium">Day</th>
                <th scope="col" className="px-2 py-2 text-right font-medium">Msgs</th>
                <th scope="col" className="px-2 py-2 text-right font-medium">Convs</th>
                <th scope="col" className="px-2 py-2 text-right font-medium">Visitors</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Errors</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {days.map((d) => (
                <tr key={d.date}>
                  <th scope="row" className="px-3 py-1.5 font-normal text-gray-200">{formatDay(d.date)}</th>
                  <td className="px-2 py-1.5 text-right">{d.messages}</td>
                  <td className="px-2 py-1.5 text-right">{d.conversations}</td>
                  <td className="px-2 py-1.5 text-right">{d.sessions}</td>
                  <td className={`px-3 py-1.5 text-right ${d.errors ? "text-rose-300" : ""}`}>{d.errors}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}
