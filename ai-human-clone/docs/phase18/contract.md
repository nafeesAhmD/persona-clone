# Phase 18 — Marketplace & clone discovery: backend ↔ frontend contract

Builds on what exists: `public_service.discover()` (public-profile search), `/explore`
(components/public/ExploreClones.tsx), the public profile `/c/[slug]` (reused — no second
profile system), `admin_disabled`, the platform switch `public_clone_discovery_enabled`,
`AnalyticsEvent` + `analytics.events.record_event`, `admin_service.audit`.

**Not implemented on purpose: ratings/reviews.** There is no way to verify that a reviewer
actually talked to a clone, and the phase forbids ratings that only make the marketplace look
popular. No rating, star or review count appears anywhere.

## Data (migration `0022_marketplace`)

`clone_profiles` (all default off/empty for existing clones):
| column | type | notes |
|---|---|---|
| `marketplace_enabled` | bool, default false | owner opt-in |
| `marketplace_category` | varchar(40) null | one of the fixed category slugs |
| `marketplace_tags` | JSON list[str], default [] | ≤ 8 tags, each 2–30 chars, lowercase, `[a-z0-9 +#.-]` |
| `short_description` | varchar(200) null | plain text |
| `featured_rank` | int null | admin only; lower = earlier; null = not featured |
| `published_at` | timestamptz null | set the first time it becomes eligible+enabled; cleared on opt-out |
| `marketplace_suspended` | bool, default false | admin moderation |
| `marketplace_suspended_reason` | varchar(200) null | **internal**, never in public/owner responses (owner sees only "suspended") |

Indexes: (marketplace_enabled, marketplace_suspended, visibility, status), marketplace_category,
published_at, featured_rank; on PostgreSQL a GIN full-text index over the public search text
(see Search). Existing `skills` = "expertise".

Tables:
* `favorite_clones` — id, user_id → users (cascade), clone_id → clone_profiles (cascade), created_at; **unique(user_id, clone_id)**.
* `clone_reports` — id, reporter_user_id null (set null), reporter_key varchar(64) null (sha256 of IP for anonymous), clone_id (cascade), reason (`impersonation|unauthorized_voice_or_avatar|privacy|harmful_or_misleading|spam|other`), description text ≤ 1000, status (`open|reviewing|resolved|dismissed`), created_at, reviewed_at null, reviewed_by null → users, resolution_note ≤ 500 (internal, admin only).

## Eligibility (one SQL predicate, reused everywhere)

A clone is **listed** only if all hold: `visibility == "public"`, `status == "active"`,
`admin_disabled` false, owner `is_active`, `public_chat_enabled` true, `marketplace_enabled`
true, `marketplace_suspended` false, and the platform switch `public_clone_discovery_enabled`
is on (if off: list/search/featured/categories/tags return 403 `discovery_off`, as `discover()`
does today; profiles by slug keep working like `/c/[slug]`). Unlisted/private clones never
appear and a slug of an ineligible clone returns the same 404 as an unknown slug.

## Public API (no auth; optional auth only adds `is_favorite`)

Rate-limited with the existing public limiter (`check_public_rate("marketplace", ip)`).

`GET /api/marketplace/clones?q&category&tags&profession&voice_enabled&avatar_enabled&sort&page&page_size`
* `tags` comma-separated (≤ 5, each must match the tag pattern), `sort` = `relevance` (default when `q`) | `newest` (default otherwise) | `popular`; `page` ≥ 1, `page_size` 1–48 (default 24); `q` ≤ 100 chars. Invalid values → 400 (platform validation error shape).
* `voice_enabled=true` → clone's public voice is available (same rule as the public profile's `voice_enabled`); `avatar_enabled=true` likewise.
→ `MarketplacePage { items: MarketplaceCard[], total, page, page_size, sort }`

`GET /api/marketplace/search` — same as above, `q` required (1–100) and `sort` defaults to relevance; records `marketplace_search_performed`.

`GET /api/marketplace/clones/featured?limit` (≤ 12, default 8) → `MarketplaceCard[]` ordered by featured_rank then published_at desc (only clones with featured_rank).

`GET /api/marketplace/categories` → `[{slug, name, description, count}]` — all fixed categories with counts of listed clones (counts by SQL GROUP BY).
Fixed categories (slug → name): `education` Education & Tutoring, `technology` Technology & Programming, `business` Business & Career, `health` Health & Wellness, `creative` Creative & Arts, `lifestyle` Lifestyle & Hobbies, `language` Languages, `science` Science & Research, `entertainment` Entertainment, `other` Other.

`GET /api/marketplace/tags?limit` (≤ 50, default 30) → `[{tag, count}]` most used among listed clones.

`GET /api/marketplace/clones/{slug}` → `MarketplaceProfile` (404 unless listed); records `marketplace_clone_viewed` once per viewer per clone per 30 minutes (viewer = user id, else hashed IP).

```jsonc
// MarketplaceCard
{ "id": "uuid", "slug": "ayaan", "name": "Ayaan AI", "profession": "…", "short_description": "…",
  "tagline": "…", "avatar_url": "/api/public/clones/ayaan/avatar-image" | null,
  "category": {"slug","name"} | null, "tags": ["python"], "skills": ["Django"],
  "capabilities": {"chat": true, "voice": false, "avatar": false, "realtime_voice": false},
  "published_at": "iso", "featured": false }
// MarketplaceProfile = MarketplaceCard + 
{ "bio": "…", "preferred_language": "ur", "favorites": 3, "is_favorite": false,  // is_favorite only when logged in, else false
  "public_url": "/c/ayaan" }
```
Never: owner email/name/ids, private fields, moderation notes, document or memory content.

## Favorites (auth required)
* `POST /api/marketplace/favorites/{clone_id}` → 201 `{clone_id, created_at}`; 200 with the same body if already saved (idempotent, no duplicate row); 404 if not listed (same as unknown). Records `marketplace_clone_favorited` only on a new row.
* `DELETE /api/marketplace/favorites/{clone_id}` → 204 (idempotent); records `marketplace_clone_unfavorited` only if a row was deleted.
* `GET /api/marketplace/favorites?page&page_size` → `MarketplacePage` of the user's saved clones that are **still listed** (others hidden, rows kept), newest saved first.

## Reports
`POST /api/marketplace/clones/{slug}/report` (auth optional; anonymous allowed) body `{reason, description?}` → 201 `{id, status:"open"}`. Rate limit: 5/hour per user or IP; one open report per reporter+clone (second → 200 with the existing report id). 404 if the slug is not publicly viewable (listed or plain public profile). Records `marketplace_clone_reported`. Description stored as plain text.

## Owner (clone owner only, `get_managed_clone` rules)
`GET /api/clones/{clone_id}/marketplace` →
```jsonc
{ "enabled": false, "category": null, "tags": [], "short_description": null,
  "published_at": null, "suspended": false,           // never the reason
  "eligible": false, "listed": false,
  "requirements": [ {"key":"public","ok":false,"label":"Clone is public"},
                    {"key":"active","ok":true,"label":"Clone is active"},
                    {"key":"public_chat","ok":false,"label":"Public chat is on"},
                    {"key":"not_disabled","ok":true,"label":"Not disabled by an administrator"},
                    {"key":"not_suspended","ok":true,"label":"Not suspended from the marketplace"},
                    {"key":"discovery_on","ok":true,"label":"Discovery is on for this platform"} ],
  "preview": MarketplaceCard,                          // how the card will look
  "public_url": "/c/slug" }
```
`PATCH /api/clones/{clone_id}/marketplace` body `{enabled?, category?, tags?, short_description?, confirm_publish?}` → same shape. Turning `enabled` from false to true requires `confirm_publish: true` (else 409 `confirmation_required`) and all requirements except discovery_on (else 409 `not_eligible` with the failing keys). Turning it off (remove from discovery) never needs confirmation and keeps all other settings/visibility untouched; clears `published_at`. Validation errors → 400/422 per platform convention.
`GET /api/clones/{clone_id}/marketplace/analytics?days=30` (≤ 90) → `{ views, favorites, public_chat_starts, daily: [{date, views, favorites}] }` — views = `marketplace_clone_viewed` events (already de-duplicated), favorites = current count, public_chat_starts = public chat sessions created in the window. "Search appearances" are **not** measured (not reliable) and are not returned.

## Admin (centralized admin auth; every change → `admin_service.audit`)
* `GET /api/admin/marketplace/reports?status&page&page_size` → reports with clone {id,name,slug}, reporter (email only for admins, or "anonymous"), reason, description, status, created_at, reviewed_at, resolution_note.
* `PATCH /api/admin/marketplace/reports/{report_id}` `{status, resolution_note?}`.
* `PATCH /api/admin/marketplace/clones/{clone_id}/visibility` `{suspended: bool, reason?, featured_rank?: int|null}` — suspend/unsuspend from the marketplace and set featured rank.
Non-admins → 403 (existing admin dependency).

## Search
Search text = name, short_description, tagline, profession, skills, marketplace_tags, category name (public metadata only; the bio is left out to keep relevance tight).
* PostgreSQL: `to_tsvector('simple', …)` with `websearch_to_tsquery('simple', q)` + `ts_rank` for relevance, plus a prefix `ILIKE` fallback so partial words match; GIN expression index in the migration.
* Other databases (tests use SQLite): escaped `LIKE` on the same fields; relevance = name match first, then newest.
All via SQLAlchemy expressions / bound parameters. No embeddings, no private data indexed.

## Ranking
* `relevance`: text rank → featured → published_at desc.
* `newest`: published_at desc.
* `popular` (transparent): favorites count + distinct public chat sessions in the last 30 days, computed with SQL aggregation; ties → newest. Message volume is not used.
Sort order is deterministic (final tie-break by id).

## Analytics events (`record_event`, source `marketplace`)
`marketplace_clone_viewed`, `marketplace_search_performed` (metadata: q length, filters, result count — not the query text), `marketplace_category_viewed` (when `category` filter used on the list endpoint, once per request), `marketplace_clone_favorited`, `marketplace_clone_unfavorited`, `marketplace_clone_reported` (reason only). Only after a successful response; never with raw text.

## Frontend routes
* `/explore` — marketplace home: search bar, featured, categories, recently published, popular, filters (category, voice, avatar, tags), cards, load more, loading/empty/error states, real API only.
* `/explore/categories` — all categories with counts.
* `/explore/[category]` — results for one category (unknown slug → 404 page).
* Profile: the existing `/c/[slug]` gains marketplace bits (category, tags, capabilities badges, ♡ save, Report, Share/copy link). No `/explore/clone/[slug]`.
* `/saved-clones` — the user's favorites (login required).
* Owner: "Marketplace" card on `/clone/[id]/sharing` (enable with confirmation dialog, category, tags editor, short description, requirement checklist, card preview, link to public profile, analytics, "Remove from marketplace").
* Admin: `/admin/marketplace` — reports list with status changes, suspend/unsuspend, featured rank.

## As built (backend)

* **Errors:** `{"detail": message, "code": code}` (+ `"failed": [keys]` on `not_eligible`). Codes:
  `discovery_off` 403, `not_found` 404, `confirmation_required` 409, `not_eligible` 409,
  `report_not_found` 404. Query/body validation keeps the platform's 400 (`validation_error`).
* **Admin clone visibility** `PATCH /api/admin/marketplace/clones/{clone_id}/visibility`: every
  field optional; only fields present in the body change (`model_fields_set`): `suspended`,
  `reason` (alone: updates the reason of a suspended clone), `featured_rank` (explicit `null`
  clears it). Setting a rank never lifts a suspension. Empty body → 400.
  Response `{clone_id, slug, marketplace_enabled, suspended, suspended_reason, featured_rank}`.
* **New:** `GET /api/admin/marketplace/clones?status=listed|suspended|featured|all&q&page&page_size`
  (default `all` = opted in, suspended or featured) →
  `{items:[{id,name,slug,marketplace_enabled,listed,suspended,suspended_reason,featured_rank,published_at,open_reports}], total, page, page_size}`.
  `listed` uses the public listing predicate; `open_reports` counts open + reviewing reports.
* Admin reports list uses `page` / `page_size` (≤ 100).
* `marketplace_search_performed` is recorded for any request with a non-empty `q`, on
  `/clones` (`metadata.endpoint = "list"`) and `/search` (`"search"`); metadata holds `q_length`,
  filter names, sort and result count — never the query text.
* **Popular tags** count the tags of the newest 2,000 listed clones in Python (one column read),
  not a SQL aggregate over JSON (portable across PostgreSQL and SQLite).
* **View de-duplication** is in-process (30 min per viewer per clone; viewer = user id or SHA-256
  of the client address). With several backend instances a viewer could be counted once per
  instance.
* Browsing is rate-limited per client address (`MARKETPLACE_RATE_LIMIT_PER_MINUTE`, default 120);
  reports per reporter per hour (`MARKETPLACE_REPORTS_PER_HOUR`, default 5).
* `MarketplaceProfile` includes `id` and `is_favorite` (false when not logged in).
