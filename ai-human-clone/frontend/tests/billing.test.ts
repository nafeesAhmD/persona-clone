import assert from "node:assert/strict";
import test from "node:test";

import {
  describeUsage,
  formatCompact,
  formatPrice,
  formatResetDate,
  formatUsage,
  isUnlimited,
  planLimitLines,
  sortByPressure,
  sortPlans,
  toneLabel,
  usagePercent,
  usageTone,
} from "../lib/usage.ts";

test("unlimited limits", () => {
  for (const value of [null, undefined, 0, -1, Number.POSITIVE_INFINITY]) assert.equal(isUnlimited(value), true);
  assert.equal(isUnlimited(5), false);
  assert.equal(usagePercent(10, null), null);
  assert.equal(usageTone(10, 0), "unlimited");
});

test("usage percent is rounded and clamped", () => {
  assert.equal(usagePercent(0, 1000), 0);
  assert.equal(usagePercent(1, 3), 33);
  assert.equal(usagePercent(1500, 1000), 100);
  assert.equal(usagePercent(-5, 10), 0);
});

test("usage tone has words, not just colors", () => {
  assert.equal(usageTone(79, 100), "ok");
  assert.equal(usageTone(80, 100), "warn");
  assert.equal(usageTone(100, 100), "over");
  assert.equal(toneLabel("over"), "Limit reached");
  assert.equal(toneLabel("warn"), "Almost at the limit");
  assert.equal(toneLabel("ok"), null);
});

test("usage text", () => {
  assert.equal(formatUsage(12, 1000), "12 of 1,000");
  assert.equal(formatUsage(3.456, 100, "MB"), "3.46 MB of 100 MB");
  assert.equal(formatUsage(7, null), "7 (unlimited)");
  assert.equal(describeUsage({ label: "Clones", used: 2, limit: 5, unit: null }), "Clones: 2 of 5 (40% used)");
  assert.equal(describeUsage({ label: "API", used: 2, limit: null, unit: null }), "API: 2 (unlimited)");
});

test("compact numbers", () => {
  assert.equal(formatCompact(950), "950");
  assert.equal(formatCompact(1200), "1.2K");
  assert.equal(formatCompact(1000), "1K");
  assert.equal(formatCompact(3_400_000), "3.4M");
  assert.equal(formatCompact(250_000), "250K");
});

test("reset date", () => {
  const now = new Date("2026-10-05T12:00:00Z");
  assert.equal(formatResetDate("2026-11-01T00:00:00Z", now), "Resets on 1 Nov 2026 (in 27 days)");
  assert.equal(formatResetDate("2026-10-06T00:00:00Z", now), "Resets on 6 Oct 2026 (in 1 day)");
  assert.equal(formatResetDate(null, now), null);
  assert.equal(formatResetDate("not a date", now), null);
});

test("plan prices and order", () => {
  assert.equal(formatPrice({ price: 0, currency: "USD", billing_interval: "month" }), "Free");
  assert.equal(formatPrice({ price: 9.99, currency: "USD", billing_interval: "month" }), "$9.99 / month");
  const plans = sortPlans([
    { slug: "b", price: 29.99, is_public: true, is_active: true },
    { slug: "hidden", price: 1, is_public: false, is_active: true },
    { slug: "f", price: 0, is_public: true, is_active: true },
  ]);
  assert.deepEqual(plans.map((p) => p.slug), ["f", "b"]);
});

test("plan limit lines", () => {
  assert.deepEqual(planLimitLines({ clones: 5, knowledge_mb: 100, chat_messages: 0, unknown: 3 }), [
    "Clones: 5",
    "Chat messages: unlimited",
    "Knowledge storage: 100 MB",
  ]);
  assert.deepEqual(planLimitLines({ voice_requests: 100 }), ["Voice transcriptions: 100 / month"]);
});

test("items nearest their limit come first", () => {
  const sorted = sortByPressure([
    { key: "a", used: 1, limit: 100 },
    { key: "b", used: 5, limit: null },
    { key: "c", used: 9, limit: 10 },
  ]);
  assert.deepEqual(sorted.map((i) => i.key), ["c", "a", "b"]);
});
