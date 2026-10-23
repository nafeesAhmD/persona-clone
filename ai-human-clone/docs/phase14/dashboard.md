# Phase 14 — Developer dashboard and admin view

## Developer dashboard (`/developer`)

Signed-in users manage the developer API from `/developer` (linked as **Developer** in the navbar).
The pages call the cookie-session API under `/api/developer/*`; the server checks ownership on every request.

| Page | What it does |
| --- | --- |
| `/developer` | Overview for the last 30 days: API requests, chat requests, successful/failed, current per-minute rate limit, this month's requests vs. the plan limit, active keys and webhooks. |
| `/developer/keys` | List keys (prefix, status, scopes, last used, expiry). Create a key with a name, explicit scopes, an expiry (never / 30 / 90 / 365 days / a date) and optionally an organization. The full key is shown **once** after create or rotate ("Copy this key now. You will not be able to see it again."), kept only in page memory and dropped when hidden. Rotate, revoke and delete ask for confirmation. |
| `/developer/webhooks` | Add an endpoint URL with event checkboxes (the signing secret is shown once), enable/disable, send a test event, rotate the secret, delete, and a per-webhook delivery history with **Retry** for failed deliveries. |
| `/developer/usage` | Requests and errors per day, by endpoint (with average duration) and by key, for 1/7/30/90 days. |
| `/developer/docs` | Authentication, keys, scopes, every endpoint group, webhook signature verification (Node.js and Python), errors, rate limits and copy-paste curl / JavaScript / Python examples. The base URL comes from `NEXT_PUBLIC_API_URL`; the full reference is Swagger at `/api/v1/docs`. |

Organization owners and admins can switch the overview and usage pages to an organization
(`?organization_id=` on the API); other members get `403`.

### Dashboard API

- `GET /api/developer/overview[?organization_id=]` →
  `{plan, api_requests_30d, chat_requests_30d, successful_requests_30d, failed_requests_30d, monthly_requests, monthly_limit, rate_limit_per_minute, active_keys, active_webhooks}` (`monthly_limit` 0 = unlimited).
- `GET /api/developer/usage?days=1..90[&organization_id=]` →
  `{days, per_day:[{day, requests, errors}], by_endpoint:[{endpoint, requests, errors, avg_duration_ms}], by_key:[{key_id, name, key_prefix, requests}]}`.

Both count `API_REQUEST` usage events that carry an API key id and belong to the owner (personal: the user with
no organization; organization: that organization), so history of deleted keys still counts and shows as "(deleted key)".
Endpoints are stored with ids masked (`GET /api/v1/clones/{id}`). No key, key hash or secret is ever returned.

## Admin view (`/admin/developer`)

Admins (server-checked `require_admin`) see platform-wide numbers and can revoke any key.

- `GET /api/admin/developer/overview` → requests (24h / 30d), active / revoked / expired keys, active webhooks,
  failed webhook deliveries (24h), rate-limit events (24h, `API_ERROR` with status 429), API errors (24h), top endpoints,
  usage by organization and usage by plan (30 days).
- `GET /api/admin/developer/keys?page&limit&search&status` → paginated keys with prefix, owner (email or organization
  name), scopes, status and last use. Search matches key name, prefix, owner email and organization name.
- `POST /api/admin/developer/keys/{id}/revoke {reason?}` → revokes the key and writes an `API_KEY_REVOKED` admin audit
  entry (prefix, before/after, optional reason) in the same transaction. Revoking an already revoked key is a no-op.

Tests: `backend/tests/test_developer_dashboard.py`.
