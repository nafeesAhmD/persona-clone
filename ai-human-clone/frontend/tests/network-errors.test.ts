import assert from "node:assert/strict";
import test from "node:test";

import {
  RETRYABLE_KINDS,
  classifyFetchFailure,
  classifyStatus,
  defaultMessage,
  isSafeMethod,
  isUsageLimitMessage,
  shouldAutoRetry,
} from "../lib/pwa/errors.ts";

test("HTTP statuses map to kinds", () => {
  const kind = (status: number, message = "x", extra: { maintenance?: boolean; detail?: unknown } = {}) =>
    classifyStatus({ status, message, ...extra });
  assert.equal(kind(401), "auth");
  assert.equal(kind(403), "forbidden");
  assert.equal(kind(404), "not_found");
  assert.equal(kind(410), "not_found");
  assert.equal(kind(400), "invalid");
  assert.equal(kind(409), "invalid");
  assert.equal(kind(413), "invalid");
  assert.equal(kind(422), "invalid");
  assert.equal(kind(408), "timeout");
  assert.equal(kind(500), "server");
  assert.equal(kind(502), "unavailable");
  assert.equal(kind(504), "unavailable");
  assert.equal(kind(503, "LLM provider not configured"), "unavailable");
  assert.equal(kind(503, "Maintenance", { maintenance: true }), "maintenance");
});

test("429: rate limit vs usage limit", () => {
  const kind = (message: string, detail?: unknown) => classifyStatus({ status: 429, message, detail });
  assert.equal(kind("Too many requests. Please wait a moment and try again."), "rate_limit");
  assert.equal(kind("Too many login attempts. Please wait a minute and try again."), "rate_limit");
  assert.equal(kind("Claude rate limit reached"), "rate_limit");
  assert.equal(kind("You have reached your messages limit."), "usage_limit");
  assert.equal(kind("Monthly chat messages limit reached (100)."), "usage_limit");
  assert.equal(kind("Usage limit reached."), "usage_limit");
  assert.equal(kind("anything", { message: "x", limit: 10, used: 10 }), "usage_limit", "structured detail");
  assert.equal(isUsageLimitMessage("Gemini rate limit or free-tier quota reached"), false);
});

test("fetch failures: offline, timeout, unreachable", () => {
  assert.equal(classifyFetchFailure({ online: false, timedOut: false }), "offline");
  assert.equal(classifyFetchFailure({ online: true, timedOut: false }), "network");
  assert.equal(classifyFetchFailure({ online: true, timedOut: true }), "timeout");
  assert.equal(classifyFetchFailure({ online: false, timedOut: true }), "timeout");
});

test("never retry writes automatically", () => {
  for (const method of ["POST", "PATCH", "PUT", "DELETE", "post"]) {
    assert.equal(isSafeMethod(method), false);
    for (const kind of RETRYABLE_KINDS) assert.equal(shouldAutoRetry(method, kind, 0), false, `${method} ${kind}`);
  }
  assert.equal(isSafeMethod(undefined), true, "fetch defaults to GET");
  assert.equal(shouldAutoRetry("GET", "network", 0), true);
  assert.equal(shouldAutoRetry(undefined, "unavailable", 0), true);
  assert.equal(shouldAutoRetry("GET", "network", 1), false, "at most one retry");
  assert.equal(shouldAutoRetry("GET", "timeout", 0), false, "timeouts are not retried");
  assert.equal(shouldAutoRetry("GET", "offline", 0), false);
  assert.equal(shouldAutoRetry("GET", "maintenance", 0), false);
  assert.equal(shouldAutoRetry("GET", "rate_limit", 0), false);
  assert.equal(shouldAutoRetry("GET", "auth", 0), false);
});

test("default messages are user-facing, without internals", () => {
  assert.equal(defaultMessage("offline"), "You are offline. Some features may be unavailable.");
  for (const kind of ["timeout", "network", "maintenance", "unavailable", "auth", "server"] as const) {
    const text = defaultMessage(kind);
    assert.ok(text.length > 0);
    assert.doesNotMatch(text, /Error:|at \w+ \(|Traceback|stack/i);
  }
});
