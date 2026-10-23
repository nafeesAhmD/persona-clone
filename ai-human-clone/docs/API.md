# API reference

Generated from the running FastAPI app's route table (`app.main`), so it lists exactly what the backend serves.
Auth column: **public** = no login; **login** = session cookie (HttpOnly) of a logged-in user — ownership/role checks happen
inside the handler (e.g. clone owner, organization role); **admin** = platform administrator; **API key** = `Authorization: Bearer ahc_live_…`
with the endpoint's scope; **one-time ticket** = the real-time voice WebSocket ticket from `POST …/realtime/session`.
Public visitor endpoints under `/api/public/…` use the `X-Public-Session` chat token where a session is needed.

Interactive docs: `/docs` (all endpoints; off when `API_DOCS_ENABLED=false`, the production default) and
`/api/v1/docs` (the public developer API, always on). Errors use `{"detail": …}` (plus `code`/`request_id` where the area defines them).

Total: 246 routes.

## AI agent

| Method | Path | Auth |
| --- | --- | --- |
| GET | `/api/agent/executions/{execution_id}` | login |
| POST | `/api/agent/executions/{execution_id}/cancel` | login |
| POST | `/api/agent/executions/{execution_id}/confirm` | login |
| POST | `/api/agent/executions/{execution_id}/memory-proposal` | login |
| POST | `/api/agent/executions/{execution_id}/reject` | login |

## Administration

| Method | Path | Auth |
| --- | --- | --- |
| GET | `/api/admin/audit-logs` | admin |
| GET | `/api/admin/clones` | admin |
| GET | `/api/admin/clones/{clone_id}` | admin |
| PATCH | `/api/admin/clones/{clone_id}/status` | admin |
| POST | `/api/admin/content/clones/{clone_id}/disable` | admin |
| POST | `/api/admin/content/clones/{clone_id}/make-private` | admin |
| POST | `/api/admin/content/documents/{document_id}/make-private` | admin |
| POST | `/api/admin/content/memories/{memory_id}/make-private` | admin |
| GET | `/api/admin/content/public-clones` | admin |
| GET | `/api/admin/content/public-documents` | admin |
| GET | `/api/admin/content/public-memories` | admin |
| GET | `/api/admin/dashboard` | admin |
| GET | `/api/admin/developer/keys` | admin |
| POST | `/api/admin/developer/keys/{key_id}/revoke` | admin |
| GET | `/api/admin/developer/overview` | admin |
| GET | `/api/admin/marketplace/clones` | admin |
| PATCH | `/api/admin/marketplace/clones/{clone_id}/visibility` | admin |
| GET | `/api/admin/marketplace/reports` | admin |
| PATCH | `/api/admin/marketplace/reports/{report_id}` | admin |
| GET | `/api/admin/security/events` | admin |
| GET | `/api/admin/settings` | admin |
| PATCH | `/api/admin/settings` | admin |
| GET | `/api/admin/system/errors` | admin |
| GET | `/api/admin/system/health` | admin |
| GET | `/api/admin/usage` | admin |
| GET | `/api/admin/users` | admin |
| GET | `/api/admin/users/{user_id}` | admin |
| PATCH | `/api/admin/users/{user_id}/status` | admin |

## Authentication

| Method | Path | Auth |
| --- | --- | --- |
| POST | `/api/auth/change-password` | login |
| POST | `/api/auth/login` | public |
| POST | `/api/auth/logout` | public |
| GET | `/api/auth/me` | login |
| POST | `/api/auth/register` | public |

## Billing

| Method | Path | Auth |
| --- | --- | --- |
| POST | `/api/billing/cancel` | login |
| POST | `/api/billing/checkout` | login |
| GET | `/api/billing/plans` | public |
| POST | `/api/billing/portal` | login |
| GET | `/api/billing/subscription` | login |
| GET | `/api/billing/usage` | login |
| POST | `/api/billing/webhooks/{provider}` | public |

## Clones (and everything under a clone)

| Method | Path | Auth |
| --- | --- | --- |
| GET | `/api/clones` | login |
| POST | `/api/clones` | login |
| GET | `/api/clones/public` | public |
| DELETE | `/api/clones/{clone_id}` | login |
| GET | `/api/clones/{clone_id}` | login |
| PATCH | `/api/clones/{clone_id}` | login |
| GET | `/api/clones/{clone_id}/agent` | login |
| PATCH | `/api/clones/{clone_id}/agent` | login |
| GET | `/api/clones/{clone_id}/agent/executions` | login |
| POST | `/api/clones/{clone_id}/agent/run` | login |
| PUT | `/api/clones/{clone_id}/agent/tools/{tool_name}` | login |
| GET | `/api/clones/{clone_id}/analytics/activity` | login |
| GET | `/api/clones/{clone_id}/analytics/agent` | login |
| GET | `/api/clones/{clone_id}/analytics/overview` | login |
| DELETE | `/api/clones/{clone_id}/avatar` | login |
| GET | `/api/clones/{clone_id}/avatar` | login |
| PATCH | `/api/clones/{clone_id}/avatar` | login |
| POST | `/api/clones/{clone_id}/avatar` | login |
| POST | `/api/clones/{clone_id}/avatar/generate` | login |
| GET | `/api/clones/{clone_id}/avatar/jobs/{job_id}` | login |
| POST | `/api/clones/{clone_id}/avatar/jobs/{job_id}/cancel` | login |
| GET | `/api/clones/{clone_id}/avatar/jobs/{job_id}/video` | login |
| POST | `/api/clones/{clone_id}/avatar/test` | login |
| POST | `/api/clones/{clone_id}/avatar/video` | login |
| DELETE | `/api/clones/{clone_id}/avatar/{avatar_id}` | login |
| GET | `/api/clones/{clone_id}/avatar/{avatar_id}/image` | login |
| POST | `/api/clones/{clone_id}/chat` | login |
| GET | `/api/clones/{clone_id}/chat-profile` | login |
| POST | `/api/clones/{clone_id}/chat/stream` | login |
| GET | `/api/clones/{clone_id}/conversations` | login |
| GET | `/api/clones/{clone_id}/documents` | login |
| POST | `/api/clones/{clone_id}/documents` | login |
| DELETE | `/api/clones/{clone_id}/documents/{document_id}` | login |
| GET | `/api/clones/{clone_id}/documents/{document_id}` | login |
| POST | `/api/clones/{clone_id}/documents/{document_id}/index` | login |
| POST | `/api/clones/{clone_id}/documents/{document_id}/reindex` | login |
| POST | `/api/clones/{clone_id}/documents/{document_id}/retry` | login |
| PATCH | `/api/clones/{clone_id}/documents/{document_id}/visibility` | login |
| POST | `/api/clones/{clone_id}/knowledge` | login |
| POST | `/api/clones/{clone_id}/knowledge/search` | login |
| GET | `/api/clones/{clone_id}/live-avatar` | login |
| POST | `/api/clones/{clone_id}/live-avatar/face` | login |
| PUT | `/api/clones/{clone_id}/live-avatar/face-id` | login |
| GET | `/api/clones/{clone_id}/live-call` | login |
| POST | `/api/clones/{clone_id}/live-call` | login |
| POST | `/api/clones/{clone_id}/live-call/end` | login |
| GET | `/api/clones/{clone_id}/marketplace` | login |
| PATCH | `/api/clones/{clone_id}/marketplace` | login |
| GET | `/api/clones/{clone_id}/marketplace/analytics` | login |
| DELETE | `/api/clones/{clone_id}/memories` | login |
| GET | `/api/clones/{clone_id}/memories` | login |
| POST | `/api/clones/{clone_id}/memories` | login |
| POST | `/api/clones/{clone_id}/memories/clear` | login |
| DELETE | `/api/clones/{clone_id}/memories/{memory_id}` | login |
| GET | `/api/clones/{clone_id}/memories/{memory_id}` | login |
| PATCH | `/api/clones/{clone_id}/memories/{memory_id}` | login |
| POST | `/api/clones/{clone_id}/memories/{memory_id}/approve` | login |
| POST | `/api/clones/{clone_id}/memories/{memory_id}/reject` | login |
| PATCH | `/api/clones/{clone_id}/memories/{memory_id}/visibility` | login |
| GET | `/api/clones/{clone_id}/public-settings` | login |
| PATCH | `/api/clones/{clone_id}/public-settings` | login |
| POST | `/api/clones/{clone_id}/realtime/session` | login |
| GET | `/api/clones/{clone_id}/realtime/session/{session_id}` | login |
| POST | `/api/clones/{clone_id}/realtime/session/{session_id}/end` | login |
| GET | `/api/clones/{clone_id}/realtime/settings` | login |
| PATCH | `/api/clones/{clone_id}/realtime/settings` | login |
| PATCH | `/api/clones/{clone_id}/slug` | login |
| POST | `/api/clones/{clone_id}/voice/chat` | login |
| DELETE | `/api/clones/{clone_id}/voice/clone` | login |
| GET | `/api/clones/{clone_id}/voice/clone` | login |
| PATCH | `/api/clones/{clone_id}/voice/clone` | login |
| POST | `/api/clones/{clone_id}/voice/clone` | login |
| GET | `/api/clones/{clone_id}/voice/settings` | login |
| PATCH | `/api/clones/{clone_id}/voice/settings` | login |
| POST | `/api/clones/{clone_id}/voice/test` | login |
| POST | `/api/clones/{clone_id}/voice/transcribe` | login |

## Conversations

| Method | Path | Auth |
| --- | --- | --- |
| DELETE | `/api/conversations/{conversation_id}` | login |
| GET | `/api/conversations/{conversation_id}` | login |
| POST | `/api/conversations/{conversation_id}/extract-memories` | login |
| POST | `/api/conversations/{conversation_id}/messages/{message_id}/speech` | login |

## Developer platform (keys, webhooks, usage)

| Method | Path | Auth |
| --- | --- | --- |
| GET | `/api/developer/keys` | login |
| POST | `/api/developer/keys` | login |
| GET | `/api/developer/keys/scopes` | public |
| DELETE | `/api/developer/keys/{key_id}` | login |
| GET | `/api/developer/keys/{key_id}` | login |
| PATCH | `/api/developer/keys/{key_id}` | login |
| POST | `/api/developer/keys/{key_id}/revoke` | login |
| POST | `/api/developer/keys/{key_id}/rotate` | login |
| GET | `/api/developer/overview` | login |
| GET | `/api/developer/usage` | login |
| GET | `/api/developer/webhooks` | login |
| POST | `/api/developer/webhooks` | login |
| GET | `/api/developer/webhooks/events` | public |
| DELETE | `/api/developer/webhooks/{webhook_id}` | login |
| GET | `/api/developer/webhooks/{webhook_id}` | login |
| PATCH | `/api/developer/webhooks/{webhook_id}` | login |
| GET | `/api/developer/webhooks/{webhook_id}/deliveries` | login |
| POST | `/api/developer/webhooks/{webhook_id}/deliveries/{delivery_id}/retry` | login |
| POST | `/api/developer/webhooks/{webhook_id}/rotate-secret` | login |
| POST | `/api/developer/webhooks/{webhook_id}/test` | login |

## Health

| Method | Path | Auth |
| --- | --- | --- |
| GET | `/api/health` | public |
| GET | `/api/health/live` | public |
| GET | `/api/health/llm` | login |
| GET | `/api/health/qdrant` | public |
| GET | `/api/health/ready` | public |
| GET | `/api/health/services` | public |

## Invitations

| Method | Path | Auth |
| --- | --- | --- |
| POST | `/api/invitations/{token}/accept` | login |
| POST | `/api/invitations/{token}/decline` | login |

## Marketplace

| Method | Path | Auth |
| --- | --- | --- |
| GET | `/api/marketplace/categories` | public |
| GET | `/api/marketplace/clones` | public (login optional) |
| GET | `/api/marketplace/clones/featured` | public |
| GET | `/api/marketplace/clones/{slug}` | public (login optional) |
| POST | `/api/marketplace/clones/{slug}/report` | public (login optional) |
| GET | `/api/marketplace/favorites` | login |
| DELETE | `/api/marketplace/favorites/{clone_id}` | login |
| POST | `/api/marketplace/favorites/{clone_id}` | login |
| GET | `/api/marketplace/search` | public (login optional) |
| GET | `/api/marketplace/tags` | public |

## Mobile / PWA

| Method | Path | Auth |
| --- | --- | --- |
| GET | `/api/mobile/config` | public |

## Organizations

| Method | Path | Auth |
| --- | --- | --- |
| GET | `/api/organizations` | login |
| POST | `/api/organizations` | login |
| DELETE | `/api/organizations/{organization_id}` | login |
| GET | `/api/organizations/{organization_id}` | login |
| PATCH | `/api/organizations/{organization_id}` | login |
| GET | `/api/organizations/{organization_id}/analytics/clone/{clone_id}` | login |
| GET | `/api/organizations/{organization_id}/analytics/overview` | login |
| GET | `/api/organizations/{organization_id}/clones` | login |
| DELETE | `/api/organizations/{organization_id}/clones/{clone_id}` | login |
| POST | `/api/organizations/{organization_id}/clones/{clone_id}` | login |
| GET | `/api/organizations/{organization_id}/clones/{clone_id}/documents` | login |
| POST | `/api/organizations/{organization_id}/clones/{clone_id}/documents` | login |
| DELETE | `/api/organizations/{organization_id}/clones/{clone_id}/documents/{document_id}` | login |
| GET | `/api/organizations/{organization_id}/clones/{clone_id}/documents/{document_id}` | login |
| POST | `/api/organizations/{organization_id}/clones/{clone_id}/documents/{document_id}/index` | login |
| POST | `/api/organizations/{organization_id}/clones/{clone_id}/documents/{document_id}/reindex` | login |
| POST | `/api/organizations/{organization_id}/clones/{clone_id}/documents/{document_id}/retry` | login |
| POST | `/api/organizations/{organization_id}/clones/{clone_id}/knowledge` | login |
| POST | `/api/organizations/{organization_id}/clones/{clone_id}/knowledge/search` | login |
| GET | `/api/organizations/{organization_id}/clones/{clone_id}/memories` | login |
| POST | `/api/organizations/{organization_id}/clones/{clone_id}/memories` | login |
| DELETE | `/api/organizations/{organization_id}/clones/{clone_id}/memories/{memory_id}` | login |
| GET | `/api/organizations/{organization_id}/clones/{clone_id}/memories/{memory_id}` | login |
| PATCH | `/api/organizations/{organization_id}/clones/{clone_id}/memories/{memory_id}` | login |
| POST | `/api/organizations/{organization_id}/clones/{clone_id}/memories/{memory_id}/approve` | login |
| POST | `/api/organizations/{organization_id}/clones/{clone_id}/share` | login |
| DELETE | `/api/organizations/{organization_id}/clones/{clone_id}/share/{user_id}` | login |
| GET | `/api/organizations/{organization_id}/features` | login |
| GET | `/api/organizations/{organization_id}/invitations` | login |
| POST | `/api/organizations/{organization_id}/invitations` | login |
| DELETE | `/api/organizations/{organization_id}/invitations/{invitation_id}` | login |
| POST | `/api/organizations/{organization_id}/leave` | login |
| GET | `/api/organizations/{organization_id}/members` | login |
| DELETE | `/api/organizations/{organization_id}/members/{member_id}` | login |
| PATCH | `/api/organizations/{organization_id}/members/{member_id}` | login |
| GET | `/api/organizations/{organization_id}/notifications` | login |
| POST | `/api/organizations/{organization_id}/notifications/read-all` | login |
| DELETE | `/api/organizations/{organization_id}/notifications/{notification_id}` | login |
| PATCH | `/api/organizations/{organization_id}/notifications/{notification_id}/read` | login |
| GET | `/api/organizations/{organization_id}/subscription` | login |
| POST | `/api/organizations/{organization_id}/transfer-ownership` | login |
| GET | `/api/organizations/{organization_id}/usage` | login |

## Platform status

| Method | Path | Auth |
| --- | --- | --- |
| GET | `/api/platform/status` | public |

## Public clones (visitors)

| Method | Path | Auth |
| --- | --- | --- |
| GET | `/api/public/clones` | public |
| GET | `/api/public/clones/{slug}` | public |
| GET | `/api/public/clones/{slug}/audio/{audio_id}` | public |
| GET | `/api/public/clones/{slug}/avatar-image` | public |
| GET | `/api/public/clones/{slug}/avatar/jobs/{job_id}` | public |
| GET | `/api/public/clones/{slug}/avatar/jobs/{job_id}/video` | public |
| POST | `/api/public/clones/{slug}/chat` | public |
| POST | `/api/public/clones/{slug}/messages/{message_id}/avatar` | public |
| POST | `/api/public/clones/{slug}/messages/{message_id}/speech` | public |
| POST | `/api/public/clones/{slug}/realtime/session` | public |
| POST | `/api/public/clones/{slug}/realtime/session/{session_id}/end` | public |
| DELETE | `/api/public/clones/{slug}/session` | public |
| GET | `/api/public/clones/{slug}/session` | public |
| POST | `/api/public/clones/{slug}/voice/transcribe` | public |

## Public developer API v1

| Method | Path | Auth |
| --- | --- | --- |
| GET | `/api/v1/agent/executions/{execution_id}` | API key |
| GET | `/api/v1/clones` | API key |
| GET | `/api/v1/clones/{clone_id}` | API key |
| POST | `/api/v1/clones/{clone_id}/agent/run` | API key |
| GET | `/api/v1/clones/{clone_id}/analytics/activity` | API key |
| GET | `/api/v1/clones/{clone_id}/analytics/overview` | API key |
| GET | `/api/v1/clones/{clone_id}/avatar/jobs/{job_id}` | API key |
| GET | `/api/v1/clones/{clone_id}/avatar/jobs/{job_id}/video` | API key |
| POST | `/api/v1/clones/{clone_id}/avatar/video` | API key |
| POST | `/api/v1/clones/{clone_id}/chat` | API key |
| GET | `/api/v1/clones/{clone_id}/conversations` | API key |
| POST | `/api/v1/clones/{clone_id}/search` | API key |
| GET | `/api/v1/clones/{clone_id}/voice/audio/{audio_id}` | API key |
| POST | `/api/v1/clones/{clone_id}/voice/chat` | API key |
| POST | `/api/v1/clones/{clone_id}/voice/transcribe` | API key |
| POST | `/api/v1/clones/{clone_id}/voice/tts` | API key |
| DELETE | `/api/v1/conversations/{conversation_id}` | API key |
| GET | `/api/v1/conversations/{conversation_id}` | API key |
| GET | `/api/v1/docs` | public |
| GET | `/api/v1/me` | API key |
| GET | `/api/v1/openapi.json` | public |

## Real-time voice (WebSocket)

| Method | Path | Auth |
| --- | --- | --- |
| WS | `/api/realtime/sessions/{session_id}/ws` | one-time ticket |

## Users

| Method | Path | Auth |
| --- | --- | --- |
| PATCH | `/api/users/me` | login |

## Voice

| Method | Path | Auth |
| --- | --- | --- |
| GET | `/api/voice/audio/{audio_id}` | login |

## root

| Method | Path | Auth |
| --- | --- | --- |
| GET | `/` | public |
