"""Developer platform (Phase 14): API keys, scopes, rate limits, usage and webhooks.

External apps call /api/v1 with `Authorization: Bearer ahc_live_...`. This package
holds the shared pieces; the routes live in app/api/v1 (public developer API) and
app/api/developer (key and webhook management for logged-in users).
"""
