# Phase 14 — Public developer API (`/api/v1`)

Call your AI Clones from your own apps. Every request needs an API key (create one at `/developer/keys`):

```
Authorization: Bearer ahc_live_...
```

- A **personal key** reaches the clones its user owns; an **organization key** only the clones assigned to that
  organization (`CloneProfile.organization_id`). Any other clone or conversation is `404 resource_not_found`.
- Calls run as the clone's owner account (same knowledge, memory and prompt as the owner's own chat), so
  conversations created through the API belong to the owner and show up in the app.
- Responses contain public profile fields only: never system prompts, personality text, private memory
  content, file paths or keys. Search returns short snippets (≤ 500 characters), chat returns source titles and scores.
- Errors: `{"error": code, "message": text, "request_id": "req_..."}` (+ `retry_after` on 429). Codes:
  `invalid_request`, `validation_error`, `authentication_failed`, `permission_denied`, `resource_not_found`,
  `rate_limit_exceeded`, `usage_limit_reached`, `provider_unavailable`, `internal_error`.
- Limits: per-minute/hour rate limits (`X-RateLimit-*` headers) and the plan's monthly `api_requests`,
  `chat_messages`, `voice_requests` (speech to text), `tts_requests` and `avatar_requests`.
- Full reference: Swagger at `/api/v1/docs`, schema at `/api/v1/openapi.json`.

## Endpoints

| Method | Path | Scope(s) | Notes |
| --- | --- | --- | --- |
| GET | `/api/v1/me` | any key | Key name, owner type, scopes, rate limit |
| GET | `/api/v1/clones` | `clone:read` | `{"data": [clone...]}` |
| GET | `/api/v1/clones/{clone_id}` | `clone:read` | id, name, slug, tagline, profession, skills, preferred_language, visibility, status, voice_enabled, avatar_enabled, timestamps |
| POST | `/api/v1/clones/{clone_id}/chat` | `clone:chat` | `{"message", "conversation_id": null}` → `{conversation_id, message_id, message, sources:[{title, score}], memories_used, created_at}`; counts toward `chat_messages` |
| GET | `/api/v1/clones/{clone_id}/conversations` | `conversation:read` | The owner's conversations with the clone |
| GET | `/api/v1/conversations/{conversation_id}` | `conversation:read` | With `messages: [{id, role, content, input_mode, created_at}]` |
| DELETE | `/api/v1/conversations/{conversation_id}` | `conversation:write` | `204` |
| POST | `/api/v1/clones/{clone_id}/search` | `clone:search` *or* `clone:knowledge:read` | `{"query", "top_k": 5}` → `{query, scope, results:[{title, source_type, score, snippet}]}`. `clone:search` = all knowledge; `clone:knowledge:read` alone = documents marked public only |
| POST | `/api/v1/clones/{clone_id}/voice/transcribe` | `voice:transcribe` | multipart `audio` → `{text, language, duration_seconds}` |
| POST | `/api/v1/clones/{clone_id}/voice/chat` | `voice:transcribe` + `voice:tts` + `clone:chat` | multipart `audio` (+ `conversation_id`) → transcript, answer, `audio_url`, sources |
| POST | `/api/v1/clones/{clone_id}/voice/tts` | `voice:tts` | `{"text"}` (≤ 1000 chars) → `{audio_url}` |
| GET | `/api/v1/clones/{clone_id}/voice/audio/{audio_id}` | `voice:tts` | The generated audio (expires) |
| POST | `/api/v1/clones/{clone_id}/avatar/video` | `avatar:generate` | `{"text"}` (test video) or `{"conversation_id", "message_id"}` (an answer) → `202` job |
| GET | `/api/v1/clones/{clone_id}/avatar/jobs/{job_id}` | `avatar:generate` | `{job_id, status, progress, video_url, ...}` — poll until `completed` |
| GET | `/api/v1/clones/{clone_id}/avatar/jobs/{job_id}/video` | `avatar:generate` | The MP4 |
| GET | `/api/v1/clones/{clone_id}/analytics/overview?range=30d` | `analytics:read` | Counts only; `range` = today, yesterday, 7d, 30d, 90d |
| GET | `/api/v1/clones/{clone_id}/analytics/activity?range=30d` | `analytics:read` | `days: [{date, conversations, messages}]` |

Voice needs the owner's voice consent with voice turned on (otherwise `403`); an unconfigured voice provider gives
`503 provider_unavailable`. Avatar videos also need avatar consent, the avatar turned on and a ready avatar.
`audio_url` / `video_url` are API routes: download them with the same key.

Each call is recorded as an `API_REQUEST` (or `API_ERROR`) usage event, plus `API_CHAT`, `API_SEARCH`,
`API_VOICE` or `API_AVATAR` for the specific operation — ids, sizes and durations only, never message text.

## Examples

### curl

```bash
export AHC_KEY="ahc_live_..."
curl -s https://your-server/api/v1/clones -H "Authorization: Bearer $AHC_KEY"

curl -s https://your-server/api/v1/clones/$CLONE_ID/chat \
  -H "Authorization: Bearer $AHC_KEY" -H "Content-Type: application/json" \
  -d '{"message": "What technologies have you worked with?", "conversation_id": null}'

curl -s https://your-server/api/v1/clones/$CLONE_ID/voice/transcribe \
  -H "Authorization: Bearer $AHC_KEY" -F "audio=@question.wav"
```

### JavaScript

```js
const BASE = "https://your-server/api/v1";
const headers = { Authorization: `Bearer ${process.env.AHC_KEY}`, "Content-Type": "application/json" };

async function ask(cloneId, message, conversationId = null) {
  const res = await fetch(`${BASE}/clones/${cloneId}/chat`, {
    method: "POST",
    headers,
    body: JSON.stringify({ message, conversation_id: conversationId }),
  });
  const body = await res.json();
  if (!res.ok) throw new Error(`${body.error}: ${body.message} (${body.request_id})`);
  return body; // { conversation_id, message, sources, ... }
}

const first = await ask(CLONE_ID, "Hi! What do you do?");
const next = await ask(CLONE_ID, "Tell me more.", first.conversation_id);
```

### Python

```python
import os
import requests

BASE = "https://your-server/api/v1"
session = requests.Session()
session.headers["Authorization"] = f"Bearer {os.environ['AHC_KEY']}"

clones = session.get(f"{BASE}/clones").json()["data"]
reply = session.post(f"{BASE}/clones/{clones[0]['id']}/chat", json={"message": "Hello!"}).json()
print(reply["message"], [s["title"] for s in reply["sources"]])

hits = session.post(f"{BASE}/clones/{clones[0]['id']}/search", json={"query": "pricing", "top_k": 3}).json()
for hit in hits["results"]:
    print(hit["score"], hit["title"], hit["snippet"][:80])
```
