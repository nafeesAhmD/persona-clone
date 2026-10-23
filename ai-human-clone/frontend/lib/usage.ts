// Pure helpers for usage, limits and plans (no React, no DOM): tested in tests/billing.test.ts.
import type { Plan, UsageItem } from "@/types/billing";

export type UsageTone = "ok" | "warn" | "over" | "unlimited";

/** Readable names for plan limit keys. */
export const LIMIT_LABELS: Record<string, string> = {
  chat_messages: "Chat messages",
  clones: "Clones",
  documents: "Knowledge documents",
  knowledge_mb: "Knowledge storage",
  voice_requests: "Voice transcriptions",
  tts_requests: "Spoken replies",
  avatar_requests: "Avatar videos",
  public_chat_requests: "Public chat messages",
  api_requests: "API requests",
  api_rate_limit_per_minute: "API requests per minute",
  agent_executions: "AI agent runs",
};

/** Limits shown on plan cards, in this order. */
export const PLAN_HIGHLIGHTS = ["clones", "chat_messages", "documents", "knowledge_mb", "voice_requests", "avatar_requests", "api_requests", "agent_executions"];

/** A limit that means "unlimited": missing, null, 0 or negative. */
export function isUnlimited(limit: number | null | undefined): boolean {
  return limit === null || limit === undefined || !Number.isFinite(limit) || limit <= 0;
}

/** Percentage used, 0–100 (clamped), or null when unlimited. */
export function usagePercent(used: number, limit: number | null | undefined): number | null {
  if (isUnlimited(limit)) return null;
  const value = (Math.max(0, used) / (limit as number)) * 100;
  return Math.min(100, Math.round(value));
}

/** ok below 80%, warn from 80%, over at or above the limit. */
export function usageTone(used: number, limit: number | null | undefined): UsageTone {
  if (isUnlimited(limit)) return "unlimited";
  if (used >= (limit as number)) return "over";
  if (used / (limit as number) >= 0.8) return "warn";
  return "ok";
}

/** Words for the tone, so the state never depends on color alone. */
export function toneLabel(tone: UsageTone): string | null {
  if (tone === "over") return "Limit reached";
  if (tone === "warn") return "Almost at the limit";
  return null;
}

export function formatNumber(value: number, maxFractionDigits = 0): string {
  return value.toLocaleString("en-US", { maximumFractionDigits: maxFractionDigits });
}

/** Short numbers for small cards: 950, 1.2K, 3.4M. */
export function formatCompact(value: number): string {
  const abs = Math.abs(value);
  if (abs < 1000) return formatNumber(value);
  if (abs < 1_000_000) return `${trim(value / 1000)}K`;
  return `${trim(value / 1_000_000)}M`;
}

function trim(value: number): string {
  return value >= 100 ? Math.round(value).toString() : value.toFixed(1).replace(/\.0$/, "");
}

function withUnit(value: number, unit: string | null | undefined): string {
  const text = formatNumber(value, unit ? 2 : 0);
  return unit ? `${text} ${unit}` : text;
}

/** "12 of 1,000", "3.5 MB of 100 MB", "12 (unlimited)". */
export function formatUsage(used: number, limit: number | null | undefined, unit?: string | null): string {
  if (isUnlimited(limit)) return `${withUnit(used, unit)} (unlimited)`;
  return `${withUnit(used, unit)} of ${withUnit(limit as number, unit)}`;
}

/** Full sentence for screen readers and the visible text under a bar. */
export function describeUsage(item: Pick<UsageItem, "label" | "used" | "limit" | "unit">): string {
  const percent = usagePercent(item.used, item.limit);
  const base = `${item.label}: ${formatUsage(item.used, item.limit, item.unit)}`;
  return percent === null ? base : `${base} (${percent}% used)`;
}

const DAY_MS = 24 * 60 * 60 * 1000;

/** "Resets on 1 Nov 2026 (in 27 days)". Null when there's no date. */
export function formatResetDate(iso: string | null | undefined, now: Date = new Date()): string | null {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  const label = date.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
  const days = Math.ceil((date.getTime() - now.getTime()) / DAY_MS);
  if (days <= 0) return `Resets on ${label}`;
  return `Resets on ${label} (in ${days} ${days === 1 ? "day" : "days"})`;
}

/** "Free", "$9.99 / month". */
export function formatPrice(plan: Pick<Plan, "price" | "currency" | "billing_interval">): string {
  if (!plan.price) return "Free";
  let amount: string;
  try {
    amount = new Intl.NumberFormat("en-US", { style: "currency", currency: plan.currency || "USD" }).format(plan.price);
  } catch {
    amount = `${plan.price} ${plan.currency}`;
  }
  return `${amount} / ${plan.billing_interval || "month"}`;
}

/** Public, active plans from cheapest to most expensive. */
export function sortPlans<T extends Pick<Plan, "price" | "is_public" | "is_active">>(plans: T[]): T[] {
  return plans.filter((p) => p.is_public && p.is_active).sort((a, b) => a.price - b.price);
}

/** One line per highlighted limit of a plan: "5 clones" style text. */
export function planLimitLines(limits: Record<string, number>): string[] {
  return PLAN_HIGHLIGHTS.filter((key) => key in limits).map((key) => {
    const label = LIMIT_LABELS[key] ?? key;
    const value = limits[key];
    if (isUnlimited(value)) return `${label}: unlimited`;
    return `${label}: ${formatNumber(value)}${key === "knowledge_mb" ? " MB" : ""}${isMonthly(key) ? " / month" : ""}`;
  });
}

function isMonthly(key: string): boolean {
  return !["clones", "documents", "knowledge_mb", "api_rate_limit_per_minute"].includes(key);
}

/** Items closest to their limit first (unlimited last), so the important ones show at the top. */
export function sortByPressure<T extends Pick<UsageItem, "used" | "limit">>(items: T[]): T[] {
  return [...items].sort((a, b) => (usagePercent(b.used, b.limit) ?? -1) - (usagePercent(a.used, a.limit) ?? -1));
}
