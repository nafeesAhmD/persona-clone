# Changelog

Summarised from the git history (122 commits, 2026-09-29 → 2026-10-11) and `docs/phaseNN/`.
Dates are commit dates. Details per area live in README and `docs/`.

## Phase 20 — Final audit, QA and release (2026-10-13, completed 2026-10-15)
- Frontend QA: link checker `npm run check:links` (`frontend/scripts/check-links.mjs`), browser
  pass over the main routes at 1366 px and 390 px (Chromium only), accessible name for the clone
  form's skills input.
- Docs: ARCHITECTURE, API (generated from the route table), HACKATHON_DEMO, THIRD_PARTY_NOTICES,
  this changelog, eval dataset/results; SECURITY, PRIVACY and the final release audit.
- Backend QA: full suite **1022 passed / 0 failed** (two consecutive runs). Fixed a flaky
  message-ordering bug (random-UUID tiebreak when `created_at` values collided), stopped the
  organization member list from showing removed/suspended members' e-mail and name, and fixed a
  Windows test-id overflow in the voice tests.
- Release position: fit for local/self-hosted demo; public production still needs a deployment,
  a penetration test, real provider keys and server-side token revocation (see the audit).

## Phase 19 — Production deployment, scaling and reliability (2026-10-11)
- Startup refuses unsafe production settings (names only, never values); `/api/health/live` and
  `/api/health/ready`; API docs off in production; trusted hosts; JSON logs with request ids and
  per-request latency; DB pool and statement timeouts; migration advisory lock; bounded shutdown.
- `docker-compose.prod.yml` with Caddy (automatic HTTPS), one-shot migrate service, restricted DB
  user, Qdrant API key, no published DB/vector ports; dev compose binds Postgres/Qdrant to localhost.
- `scripts/backup.sh` / `restore.sh` (restore tested into scratch databases), GitHub Actions CI,
  deployment/env/backup/runbook/scaling docs.

## Phase 18 — Marketplace and discovery (2026-10-11)
- Owner opt-in publishing with eligibility checklist, categories, tags, short description.
- `/explore`, categories, saved clones, reports, admin moderation (suspend, featured), owner
  analytics; PostgreSQL full-text search over public profile fields only. No ratings (by design).

## Phase 17 — Real-time voice (2026-10-09 → 10-10)
- `pipeline` provider over an authenticated WebSocket: STT → the clone's chat pipeline →
  sentence-by-sentence speech; interruption/barge-in; one-time hashed tickets; limits and quotas.

## Voice cloning and Urdu speech (2026-10-06 → 10-10)
- Cloned voices via ElevenLabs or the self-hosted `voice-clone` service (Chatterbox; OmniVoice on a
  GPU, e.g. the Colab notebook), GPU-first with laptop fallback; Urdu/Roman Urdu spelled for speech
  (rules + Gemini); reference transcripts.

## Phase 16 — AI agent (2026-10-06)
- Planner, tool registry with per-clone permissions, confirmations for risky steps, limits and loop
  detection, execution history.

## Phase 15 — Mobile / PWA (2026-10-05 → 10-06)
- Service worker, offline page, install prompt, mobile navigation, responsive layouts.

## Phase 14 — Developer platform (2026-10-05)
- API keys (hashed, scoped), `/api/v1`, webhooks with HMAC signatures, SSRF protection, auto-disable.

## Phase 13 — Organizations and teams (2026-10-04 → 10-05)
- Organizations, members and roles, invitations, shared clones, org billing/usage, notifications.

## Phase 12 — Billing (2026-10-03 → 10-04)
- Plans, subscriptions, usage limits, billing events.

## Phase 11 — Analytics (2026-10-01)
- Event recording, overview metrics.

## Phase 10 — Live video call (2026-10-01)
- Simli live avatar calls.

## Phase 9 — Administration and monitoring (2026-10-01)
- Admin dashboard (users, clones, content, security, usage, system health, errors), audit logs.

## Phase 8 — Public clones and sharing (2026-10-01)
- Visibility settings, public pages `/c/[slug]`, visitor sessions, public chat/voice/avatar.

## Phase 7 — Avatar and lip-sync (2026-09-30 → 10-01)
- Avatar upload with consent, talking-avatar video jobs (local, HTTP, fal providers).

## Phase 6 — Voice (2026-09-30)
- Speech-to-text and text-to-speech, voice settings with consent, browser-voice fallback.

## Phase 5 — Long-term memory (2026-09-30)
- Memory extraction, owner approval, memory search in answers.

## Phase 4 — AI memory / vector search (2026-09-30)
- Embeddings and Qdrant indexing and retrieval.

## Phases 2–3 — Clone management and knowledge (2026-09-29)
- Clone creator and management; knowledge upload and document management.

## Phases 0–1 — Foundation (2026-09-29)
- Project skeleton, clone persistence, RAG chat, Claude/Gemini/demo providers, streaming chat,
  authentication.
