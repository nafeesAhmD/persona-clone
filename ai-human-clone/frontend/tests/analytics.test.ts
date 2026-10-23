import assert from "node:assert/strict";
import test from "node:test";

import {
  barHeights,
  describeChart,
  errorRate,
  formatDay,
  formatDuration,
  labelEvery,
  niceMax,
  parseRange,
  peakDay,
  rangeLabel,
  totals,
} from "../lib/analyticsChart.ts";
import type { DailyActivity } from "../types/analytics.ts";

const day = (date: string, messages: number, extra: Partial<DailyActivity> = {}): DailyActivity => ({
  date,
  messages,
  conversations: 0,
  sessions: 0,
  errors: 0,
  ...extra,
});

test("nice axis maximum", () => {
  assert.equal(niceMax(0), 1);
  assert.equal(niceMax(1), 1);
  assert.equal(niceMax(3), 5);
  assert.equal(niceMax(7), 10);
  assert.equal(niceMax(11), 20);
  assert.equal(niceMax(48), 50);
  assert.equal(niceMax(51), 100);
  assert.equal(niceMax(Number.NaN), 1);
});

test("bar heights scale to the axis and keep small values visible", () => {
  assert.deepEqual(barHeights([0, 5, 10]), { max: 10, heights: [0, 50, 100] });
  const { heights } = barHeights([1, 1000]);
  assert.equal(heights[0], 2); // 0.1% would be invisible
  assert.equal(heights[1], 100);
  assert.deepEqual(barHeights([]), { max: 1, heights: [] });
});

test("totals and the busiest day", () => {
  const days = [day("2026-10-01", 3, { errors: 1 }), day("2026-10-02", 7, { conversations: 2 }), day("2026-10-03", 0)];
  assert.deepEqual(totals(days), { messages: 10, conversations: 2, sessions: 0, errors: 1 });
  assert.equal(peakDay(days, "messages")?.date, "2026-10-02");
  assert.equal(peakDay(days, "sessions"), null);
});

test("chart description for screen readers", () => {
  const days = [day("2026-10-01", 3), day("2026-10-02", 7)];
  assert.equal(describeChart(days, "messages"), "10 messages from 1 Oct to 2 Oct; busiest day 2 Oct with 7.");
  assert.equal(describeChart(days, "errors"), "No errors from 1 Oct to 2 Oct.");
  assert.equal(describeChart([], "sessions"), "No visitors data.");
});

test("day labels and label spacing", () => {
  assert.equal(formatDay("2026-01-09"), "9 Jan");
  assert.equal(formatDay("bad"), "bad");
  assert.equal(labelEvery(7), 1);
  assert.equal(labelEvery(31), 5);
  assert.equal(labelEvery(91), 13);
});

test("ranges", () => {
  assert.equal(parseRange("30d"), "30d");
  assert.equal(parseRange("1y"), "7d");
  assert.equal(parseRange(null, "30d"), "30d");
  assert.equal(rangeLabel("90d"), "Last 90 days");
  assert.equal(rangeLabel("yesterday"), "Yesterday");
});

test("error rate and durations", () => {
  assert.equal(errorRate(0, 0), null);
  assert.equal(errorRate(9, 1), 10);
  assert.equal(formatDuration(null), "—");
  assert.equal(formatDuration(320.4), "320 ms");
  assert.equal(formatDuration(1400), "1.4 s");
});
