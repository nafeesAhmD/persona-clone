import assert from "node:assert/strict";
import test from "node:test";

import { CATEGORIES, categoryIcon, categoryName, isCategory } from "../lib/marketplace/categories.ts";
import {
  REPORT_REASONS,
  capabilityBadges,
  cardSummary,
  errorCode,
  marketplaceErrorMessage,
} from "../lib/marketplace/display.ts";
import {
  EMPTY_FILTERS,
  MAX_PAGE_SIZE,
  filtersFromSearchParams,
  filtersToSearchParams,
  hasActiveFilters,
  isValidTag,
  normalizeTag,
  parseTags,
  sameFilters,
} from "../lib/marketplace/filters.ts";

test("categories match the contract's fixed list", () => {
  assert.deepEqual(
    CATEGORIES.map((c) => c.slug),
    ["education", "technology", "business", "health", "creative", "lifestyle", "language", "science", "entertainment", "other"],
  );
  assert.equal(categoryName("technology"), "Technology & Programming");
  assert.equal(categoryName("nope"), null);
  assert.equal(categoryName(null), null);
  assert.ok(isCategory("health"));
  assert.ok(!isCategory("categories")); // the /explore/categories page never shadows a category
  assert.ok(!isCategory(undefined));
  assert.equal(categoryIcon("unknown"), "✨");
});

test("tag validation follows the contract pattern", () => {
  assert.equal(normalizeTag("  Data   Science "), "data science");
  for (const ok of ["python", "c++", "c#", "node.js", "machine-learning", "ai"]) assert.ok(isValidTag(ok), ok);
  for (const bad of ["a", "x".repeat(31), "<script>", "emoji😀", "under_score", "%", ""]) assert.ok(!isValidTag(bad), bad);
  assert.deepEqual(parseTags("Python, data  science,python,,<b>"), ["python", "data science"]);
  assert.deepEqual(parseTags("a1,b2,c3,d4,e5,f6,g7"), ["a1", "b2", "c3", "d4", "e5"]); // at most 5 filter tags
  assert.deepEqual(parseTags(null), []);
});

test("filters round-trip through the query string", () => {
  const filters = {
    q: "django teacher",
    category: "technology",
    tags: ["python", "c++"],
    profession: "Engineer",
    voice: true,
    avatar: false,
    sort: "popular" as const,
  };
  const params = filtersToSearchParams(filters, { page: 2, pageSize: 24 });
  assert.equal(params.get("tags"), "python,c++");
  assert.equal(params.get("voice_enabled"), "true");
  assert.equal(params.get("avatar_enabled"), null);
  assert.equal(params.get("page"), "2");
  assert.deepEqual(filtersFromSearchParams(params), filters);
  assert.ok(sameFilters(filters, filtersFromSearchParams(new URLSearchParams(params.toString()))));
});

test("invalid values are dropped, not sent", () => {
  const parsed = filtersFromSearchParams(
    new URLSearchParams("q=" + "x".repeat(150) + "&category=hacking&sort=rating&tags=%3Cb%3E,ok-tag&voice_enabled=1&avatar_enabled=true"),
  );
  assert.equal(parsed.q.length, 100);
  assert.equal(parsed.category, null);
  assert.equal(parsed.sort, null); // "rating" doesn't exist: no ratings by design
  assert.deepEqual(parsed.tags, ["ok-tag"]);
  assert.equal(parsed.voice, false); // only "true" counts
  assert.equal(parsed.avatar, true);

  const params = filtersToSearchParams({ ...EMPTY_FILTERS, sort: "relevance", category: "bogus" }, { page: 0, pageSize: 500 });
  assert.equal(params.get("sort"), null); // relevance without a query is meaningless
  assert.equal(params.get("category"), null);
  assert.equal(params.get("page"), "1");
  assert.equal(params.get("page_size"), String(MAX_PAGE_SIZE));
  assert.equal(filtersToSearchParams(EMPTY_FILTERS).toString(), "");
});

test("active filters", () => {
  assert.ok(!hasActiveFilters(EMPTY_FILTERS));
  assert.ok(!hasActiveFilters({ ...EMPTY_FILTERS, q: "   " }));
  assert.ok(hasActiveFilters({ ...EMPTY_FILTERS, avatar: true }));
  assert.ok(hasActiveFilters({ ...EMPTY_FILTERS, tags: ["python"] }));
});

test("capability badges show only what a visitor can use", () => {
  assert.deepEqual(
    capabilityBadges({ chat: true, voice: false, avatar: true, realtime_voice: true }).map((b) => b.label),
    ["Chat", "Live voice", "Avatar"],
  );
  assert.deepEqual(capabilityBadges(null), []);
  assert.deepEqual(capabilityBadges({ chat: false, voice: false, avatar: false, realtime_voice: false }), []);
});

test("card summary prefers the short description", () => {
  assert.equal(cardSummary({ short_description: " Teaches Django ", tagline: "Dev" }), "Teaches Django");
  assert.equal(cardSummary({ short_description: "  ", tagline: "Dev" }), "Dev");
  assert.equal(cardSummary({ short_description: null, tagline: null }), null);
});

test("report reasons match the contract", () => {
  assert.deepEqual(
    REPORT_REASONS.map((r) => r.value),
    ["impersonation", "unauthorized_voice_or_avatar", "privacy", "harmful_or_misleading", "spam", "other"],
  );
});

test("error codes and messages", () => {
  assert.equal(errorCode({ code: "not_eligible", detail: "x" }), "not_eligible");
  assert.equal(errorCode({ detail: { code: "confirmation_required", message: "x" } }), "confirmation_required");
  assert.equal(errorCode({ detail: "plain" }), null);
  assert.equal(errorCode(null), null);
  assert.match(marketplaceErrorMessage({ status: 403, code: "discovery_off" }), /Discovery is turned off/);
  assert.match(marketplaceErrorMessage({ status: 409, code: "confirmation_required" }), /confirm/);
  assert.match(marketplaceErrorMessage({ status: 401 }), /log in/);
  assert.match(marketplaceErrorMessage({ status: 404, message: "Clone not found" }), /isn't available/);
  assert.match(marketplaceErrorMessage({ status: 429 }), /Too many requests/);
  assert.equal(marketplaceErrorMessage({ status: 400, message: "tags: invalid" }), "tags: invalid");
  assert.match(marketplaceErrorMessage(null), /Something went wrong/);
});

test("admin visibility PATCH sends only what changes", async () => {
  const { visibilityBody } = await import("../lib/marketplace/admin.ts");
  assert.deepEqual(visibilityBody({ featured_rank: 3 }), { featured_rank: 3 }); // keeps a suspension
  assert.deepEqual(visibilityBody({ featured_rank: null }), { featured_rank: null }); // clear
  assert.deepEqual(visibilityBody({ suspended: true, reason: "  spam  " }), { suspended: true, reason: "spam" });
  assert.deepEqual(visibilityBody({ suspended: true, reason: "   " }), { suspended: true });
  assert.deepEqual(visibilityBody({ suspended: false, reason: "ignored" }), { suspended: false });
  assert.equal(visibilityBody({ suspended: true, reason: "x".repeat(300) }).reason?.length, 200);
  assert.deepEqual(visibilityBody({}), {});
});

test("admin clone list query and featured rank parsing", async () => {
  const { adminCloneParams, parseFeaturedRank } = await import("../lib/marketplace/admin.ts");
  assert.equal(adminCloneParams({ status: "featured", q: "  ayaan ", page: 2 }).toString(), "status=featured&q=ayaan&page=2&page_size=20");
  assert.equal(adminCloneParams({ status: "bogus" as never, page: 0, page_size: 999 }).toString(), "page=1&page_size=100");
  assert.equal(parseFeaturedRank(""), null);
  assert.equal(parseFeaturedRank(" 5 "), 5);
  assert.equal(parseFeaturedRank("0"), 0);
  assert.equal(parseFeaturedRank("1001"), undefined);
  assert.equal(parseFeaturedRank("-1"), undefined);
  assert.equal(parseFeaturedRank("2.5"), undefined);
});
