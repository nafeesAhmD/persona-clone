# Security

How the platform protects accounts, data and the people it represents, and where the
limits are. This describes the code as it stands in the Phase 20 audit; it is written to be
honest about what is **not** protected yet. For the audit results and release position, see
[FINAL_RELEASE_AUDIT.md](FINAL_RELEASE_AUDIT.md).

> **Scope note.** The platform has **not** been deployed publicly and has had **no formal
> penetration test**. Everything here is what the code and the automated tests do. Treat it as
> a baseline to review, not a certificate.

## Trust boundaries

| Boundary | Untrusted side | Trusted side |
|---|---|---|
| Browser ↔ API | every request body, header, file, chat message, WebSocket frame | route handlers after auth + ownership checks |
| Owner content ↔ the model | uploaded documents, memories, visitor/user messages, styles | the system prompt built only from trusted clone settings |
| API ↔ third parties | LLM, speech, lip-sync and live-avatar responses | values validated before they are stored or shown |
| API ↔ outbound webhooks | the subscriber's URL and DNS | the delivery worker after SSRF checks |
| API ↔ datastores | — | PostgreSQL, Qdrant and the file storage are internal, not exposed |

The rule throughout: **input from outside is data, never instructions** (see
[Prompt injection](#prompt-injection)), and **every resource is looked up through the
owner's identity**, never by an id taken from the request alone.

## Authentication and sessions

- **Passwords** are hashed with **Argon2id** (`app/core/security.py`, the library's
  recommended parameters) and are re-hashed on login when the parameters change. Plain
  passwords are never stored or logged.
- **No user enumeration by timing.** When an email does not exist, the login does the same
  Argon2 verification against a random dummy hash, so a failed login takes the same time
  either way. Unknown-email and wrong-password return the identical `401 Invalid email or
  password`.
- **Sessions are JWTs** (`HS256`, `type: "access"`) signed with `JWT_SECRET_KEY`, carrying
  `sub`, `iat` and `exp`. Decoding requires all three claims, pins the algorithm, and rejects
  any token whose `type` is not `access`.
- **The session lives in an `HttpOnly` cookie** (`auth_cookie_name`), so browser JavaScript
  cannot read it. Set `COOKIE_SECURE=true` in production (the app refuses to start otherwise)
  and `COOKIE_SAMESITE=lax`.
- **Sliding expiry.** `ACCESS_TOKEN_EXPIRE_MINUTES` (default 30) is the idle timeout: `GET
  /api/auth/me` re-issues the cookie on each check, so an active session stays alive while an
  idle one ends. There is currently **no absolute session lifetime** — see
  [Accepted risks](#accepted-risks-and-known-limitations).
- **Repeated failed logins** lock the account for `LOGIN_LOCKOUT_MINUTES` (default 15) after
  `LOGIN_MAX_FAILED_ATTEMPTS` (default 10). The lock is temporary and clears on success.
  Login is also rate limited per address and per email before the password is checked.
- **Password change revokes other sessions.** Changing the password stamps
  `user.sessions_valid_after`; every token issued before that moment is refused, and the
  current browser is given a fresh one. Disabled accounts are refused on the next request.
- **Logout** clears the cookie. The token itself stays valid until it expires (stateless JWT);
  see the accepted-risk note below.

## Authorization

- **Ownership first.** Clone, knowledge, memory, conversation, voice, avatar, live-call, agent
  and developer routes all resolve the resource *within the caller's account* (or an
  organization they belong to). Another user gets `404` on a private clone and `403` where the
  clone is public; an id from someone else's resource is `404`, never a leak.
- **Conversations are per-user**, including against the clone's own owner: only the user who
  had a conversation can open it.
- **Organization roles** are `owner`, `admin`, `editor`, `viewer`, enforced by a route guard;
  a member list is returned without the e-mail/name of removed or suspended members.
- **API keys** are stored hashed with a prefix and scopes, are rate limited, and can be
  rotated/revoked. Every `/api/v1` call checks the scope it needs.
- **Admin** routes require `is_admin`; moderation actions are recorded in the audit log.
- **Public endpoints use no cookies**, so they need no CSRF token; signed-in endpoints rely on
  `SameSite=Lax` and the CORS allowlist (not a per-request CSRF token).

## Data protection and isolation

- **Public/private separation** is enforced by an allowlist read from PostgreSQL at request
  time: a visitor's retrieval is filtered by `clone_id` **and** the ids of public, ready,
  indexed documents and approved public memories. An empty allowlist returns nothing, never
  everything. Making something private takes effect on the next question.
- **Memories describe the owner** and are never used when someone else chats with a public
  clone.
- **Visitor sessions** store only a SHA-256 hash of a random token, tied to one clone, with a
  TTL and a message cap. No account, e-mail or IP address is stored for a visitor, and the
  owner cannot read visitor conversations.
- **Secrets in memories** are refused by `app/services/memory_safety.py` (passwords, keys,
  tokens, card/bank words, key prefixes, private-key blocks, JWTs, Luhn-valid card numbers) —
  both AI suggestions and typed memories.
- **Generated media ownership.** Voice audio and avatar videos are served only through
  owner-checked routes and expire (`VOICE_AUDIO_RETENTION_HOURS`, `VIDEO_RETENTION_HOURS`,
  default 24 h). Raw recordings are never stored.

## Input handling

- **Uploads** are checked on the actual bytes, not the name: extension, declared MIME type and
  magic signature must agree; size is checked from `Content-Length` first and again while
  reading; images are re-encoded (metadata stripped) and checked for decompression bombs. The
  user's filename is used only as display text and never as a path, so `../` tricks and
  collisions cannot happen, and server paths are never returned.
- **SSRF (outbound webhooks)** is checked at creation *and* again at delivery: the URL is
  re-validated, DNS is re-resolved, and private/loopback/link-local targets are refused.
- **Prompt injection** is handled by never putting untrusted text in the system prompt.
  Documents, memories, user and visitor messages are wrapped in declared data tags
  (`<reference_knowledge>`, `<user_message>`), and any copy of those tags inside the text is
  neutralised so a document cannot close the block and pose as instructions. The prompt
  forbids revealing itself or describing internals.
- **Realtime voice** WebSockets require a one-time hashed ticket and a known `Origin`; a
  missing or unknown origin is refused.

## Transport, headers and platform hardening

- **Security headers on every API response** (`app/core/security_headers.py`):
  `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
  `Referrer-Policy: strict-origin-when-cross-origin`,
  `Cross-Origin-Resource-Policy: same-site`, a `default-src 'none'; frame-ancestors 'none'`
  CSP (except the docs UI), and `Cache-Control: no-store` on `/api/public/*`.
- **Trusted hosts**: `ALLOWED_HOSTS` rejects other `Host` headers (health probes exempt).
- **CORS** is an explicit allowlist; `*` is refused in production.
- **Production startup checks** (`app/core/production.py`) refuse to boot with an empty, short
  or placeholder `JWT_SECRET_KEY`, `COOKIE_SECURE=false`, non-HTTPS/localhost origins, the
  default database password, an open Qdrant, API docs enabled, or the unimplemented
  real-time-audio retention flag. Problems name the variable and reason, never its value.
- **API docs are off in production**; JSON logs carry request ids and latency, never secrets.
- **Deployment** runs behind Caddy (automatic HTTPS), a restrictive database user, a Qdrant
  API key and no published DB/vector ports. See
  [PRODUCTION_DEPLOYMENT.md](PRODUCTION_DEPLOYMENT.md).

## Abuse and cost controls

- In-process rate limiters for login, chat, voice, avatar, live calls, API keys, invitations
  and new organizations, with friendly `429` responses.
- Per-clone and per-plan usage limits (billing events), public-session message/output caps, and
  an optional vendor-neutral CAPTCHA on public sessions.
- Upload, message and media size/duration limits; the agent has loop detection and confirmation
  steps for risky tools.
- **Caveat:** rate limits and a few other counters are held **in the API process**. Run a
  single backend process, or add a shared store, or the limits do not hold across workers (the
  app warns if `WEB_CONCURRENCY>1`).

## Secrets management

- All keys come from the environment (`.env` locally, the platform's secret store in
  production) and are never committed. `JWT_SECRET_KEY` must be a random 64-char value.
- Provider keys (Anthropic, Gemini, ElevenLabs, fal, Simli) are used server-side only; the
  browser never receives them. Live-avatar sessions get a short-lived token instead.
- The repository ships `.env.example` with placeholders only. Rotate a key immediately if one
  is ever exposed; changing `JWT_SECRET_KEY` ends all sessions at once.

## Security test coverage

Automated tests in `backend/tests/` include a dedicated audit suite:

- `test_security_audit.py` — headers, auth requirements, cookie flags, token tampering,
  password-change revocation, public/private boundaries.
- `test_production.py` — startup refusal on unsafe production settings.
- Plus IDOR/authorization tests across clones, knowledge, memory, voice, avatar, organizations,
  marketplace, developer keys and webhooks (`test_clones.py`, `test_organizations.py`,
  `test_public.py`, `test_marketplace.py`, `test_developer_keys.py`, `test_webhooks.py`, …).

See [FINAL_RELEASE_AUDIT.md](FINAL_RELEASE_AUDIT.md) for the exact counts of the Phase 20 run.

## Accepted risks and known limitations

These were found in the Phase 20 audit, reviewed, and left as-is (or deferred) because fixing
them would remove a working control or needs infrastructure that is not part of this
deployment. They are **not** hidden defects; each has a rationale.

| # | Finding | Severity | Why it stands |
|---|---|---|---|
| A1 | **Logout does not revoke the JWT.** The cookie is cleared, but the stateless token stays valid until it expires (≤ `ACCESS_TOKEN_EXPIRE_MINUTES`). | Low | Needs a server-side revocation store (e.g. Redis) that this single-process deployment does not have. Password change *does* revoke all tokens. |
| A2 | **No absolute session lifetime.** `me` slides the expiry, so a long-active session never ends on its own. | Medium | Deliberate UX choice (active users stay signed in). Mitigated by the 30-minute idle timeout, `SameSite`/`HttpOnly` cookie, and password-change revocation. An absolute cap is a planned addition. |
| A3 | **Lockout reveals account existence.** A locked account returns `429 "…wait…"`, while an unknown e-mail returns `401`. | Medium | The lockout itself is a security control and is tested/documented; login is rate limited per address and per e-mail, which blunts enumeration and targeted lock-out. Removing the distinct message would weaken legitimate users' ability to recover. |
| A4 | **Password-change cut-off has 1-second granularity.** Tokens issued in the same second as the change can survive. | Low | Tokens live 30 minutes; the window is ≤ 1 s and requires racing the change. Fixing it needs per-token ids or finer `iat`. |
| C1 | **Inbound billing webhook does not verify a signature.** `POST /api/billing/webhook` is a stub that currently does nothing. | Low | No payment provider is wired up yet, so there is nothing to verify against. When a provider is added, verify its signature before acting on the event. |
| — | **No self-service account deletion / data export.** | — | Users can delete clones and memories (with their files and vectors); whole-account removal is an operator/admin action today. Tracked in [PRIVACY.md](PRIVACY.md). |
| — | **Group-chat / sharing a conversation** is not implemented, so cross-user conversation access is not a surface. | — | By design. |

## Reporting a vulnerability

This is a local/demo project without a bug-bounty or a security contact yet. If you are
reviewing it, open an issue in the project's tracker with steps to reproduce; do not include
live secrets or real personal data. Do not test against a deployment you do not own.
