// Pure helpers for the analytics screens (no React, no DOM): tested in tests/analytics.test.ts.
import type { ActivityMetric, AnalyticsRange, DailyActivity } from "@/types/analytics";

export const RANGE_OPTIONS: { value: AnalyticsRange; label: string; short: string }[] = [
  { value: "today", label: "Today", short: "Today" },
  { value: "7d", label: "Last 7 days", short: "7 days" },
  { value: "30d", label: "Last 30 days", short: "30 days" },
  { value: "90d", label: "Last 90 days", short: "90 days" },
];

export const METRIC_LABELS: Record<ActivityMetric, string> = {
  messages: "Messages",
  conversations: "Conversations",
  sessions: "Visitors",
  errors: "Errors",
};

export function rangeLabel(range: AnalyticsRange): string {
  if (range === "yesterday") return "Yesterday";
  return RANGE_OPTIONS.find((o) => o.value === range)?.label ?? range;
}

/** A value from the URL, or the default. */
export function parseRange(value: string | null | undefined, fallback: AnalyticsRange = "7d"): AnalyticsRange {
  const allowed: AnalyticsRange[] = ["today", "yesterday", "7d", "30d", "90d"];
  return allowed.includes(value as AnalyticsRange) ? (value as AnalyticsRange) : fallback;
}

/** A round axis maximum: 1, 2, 5, 10, 20, 50 … at least the largest value (and at least 1). */
export function niceMax(value: number): number {
  if (!Number.isFinite(value) || value <= 1) return 1;
  const power = 10 ** Math.floor(Math.log10(value));
  for (const step of [1, 2, 5, 10]) {
    if (step * power >= value) return step * power;
  }
  return 10 * power;
}

/** Bar heights as percentages of the axis maximum (a non-zero value always shows at least 2%). */
export function barHeights(values: number[]): { max: number; heights: number[] } {
  const max = niceMax(Math.max(0, ...values));
  const heights = values.map((v) => (v <= 0 ? 0 : Math.max(2, Math.round((v / max) * 1000) / 10)));
  return { max, heights };
}

export function totals(days: DailyActivity[]): Record<ActivityMetric, number> {
  return days.reduce(
    (sum, d) => ({
      messages: sum.messages + d.messages,
      conversations: sum.conversations + d.conversations,
      sessions: sum.sessions + d.sessions,
      errors: sum.errors + d.errors,
    }),
    { messages: 0, conversations: 0, sessions: 0, errors: 0 },
  );
}

/** The busiest day for a metric, or null when everything is zero. */
export function peakDay(days: DailyActivity[], metric: ActivityMetric): DailyActivity | null {
  let best: DailyActivity | null = null;
  for (const d of days) if (d[metric] > 0 && (!best || d[metric] > best[metric])) best = d;
  return best;
}

/** "5 Oct" for a YYYY-MM-DD day (read as UTC so it never shifts a day). */
export function formatDay(day: string): string {
  const date = new Date(`${day}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return day;
  return date.toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });
}

/** Label every n-th bar so labels never overlap: about 7 labels whatever the range. */
export function labelEvery(count: number, target = 7): number {
  return count <= target ? 1 : Math.ceil(count / target);
}

/** One sentence that describes the chart for screen readers. */
export function describeChart(days: DailyActivity[], metric: ActivityMetric): string {
  const name = METRIC_LABELS[metric].toLowerCase();
  if (days.length === 0) return `No ${name} data.`;
  const total = totals(days)[metric];
  const peak = peakDay(days, metric);
  const span = `${formatDay(days[0].date)} to ${formatDay(days[days.length - 1].date)}`;
  if (!peak) return `No ${name} from ${span}.`;
  return `${total} ${name} from ${span}; busiest day ${formatDay(peak.date)} with ${peak[metric]}.`;
}

/** Error rate as a whole percent, or null when there were no requests. */
export function errorRate(successful: number, failed: number): number | null {
  const total = successful + failed;
  return total > 0 ? Math.round((failed / total) * 100) : null;
}

/** "320 ms", "1.4 s", or "—". */
export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || !Number.isFinite(ms)) return "—";
  return ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`;
}
