# Phase 17 — Real-time voice: backend ↔ frontend contract

Implemented provider: **`pipeline`** — a server-orchestrated real-time loop over an
authenticated **WebSocket**. No new paid service: each turn reuses the platform's own
speech-to-text (`app/voice/speech_to_text.py`), the clone's normal chat pipeline (prompt,
RAG, approved memories, history — `chat_service` / `public_service`), and the clone's
voice (`text_to_speech` with `routing.effective_voice`: cloned voice or AI voice),
synthesised **sentence by sentence while the answer streams**, so the first sentence
plays before the whole answer is written.

Why WebSocket, not WebRTC: WebRTC needs either a media server (SFU/TURN) or a provider
that terminates it (OpenAI Realtime, Gemini Live). Those providers replace the clone's
Claude/RAG pipeline with their own model, which Phase 17 forbids doing silently. The
provider interface (`RealtimeProvider`) leaves room for such an adapter later; none is
implemented or claimed.

Honest latency: STT ≈ 1–5 s (Gemini), first answer sentence ≈ 1–3 s (LLM streaming),
speech per sentence = the TTS provider's speed (Gemini TTS: seconds; self-hosted cloned
voice on a CPU: about a minute; on a Colab GPU: seconds). Speech mode `browser` speaks the
streamed text with the browser's own voice instantly (not the clone's voice).

## Settings (per clone, owner only)

`GET  /api/clones/{clone_id}/realtime/settings` → `RealtimeSettings`
`PATCH /api/clones/{clone_id}/realtime/settings` ← `RealtimeSettingsUpdate` → `RealtimeSettings`

```jsonc
// RealtimeSettings
{
  "available": true,              // REALTIME_VOICE_ENABLED and a provider configured
  "reason": null,                 // why not available: "disabled" | "provider_not_configured" | "voice_off" | "consent_missing"
  "provider": "pipeline",
  "enabled": true,                // clone_profiles.realtime_voice_enabled (owner switch)
  "public_enabled": false,        // clone_profiles.public_realtime_voice_enabled (default false)
  "speech_mode": "voice",         // "voice" (server TTS: cloned/AI voice) | "browser" (browser speechSynthesis)
  "capabilities": {
    "transport": "websocket",
    "interruption": true,
    "streaming_text": true,
    "server_speech": true,        // a TTS provider is configured
    "cloned_voice": true,         // this clone speaks with its cloned voice
    "languages": ["en", "ur", "roman-ur"]   // what the configured STT/TTS can do; see docs
  },
  "limits": { "max_duration_seconds": 600, "session_ttl_seconds": 600, "max_utterance_seconds": 30, "max_utterance_bytes": 2000000 }
}
// RealtimeSettingsUpdate (all optional)
{ "enabled": true, "public_enabled": false, "speech_mode": "browser" }
```

`public_enabled` can only be true while the clone is public, public chat is on and
`public_voice_enabled` is on (422 otherwise).

## Sessions (logged-in users; chat rules = `clone_service.get_chat_clone`)

`POST /api/clones/{clone_id}/realtime/session` (body optional: `{ "conversation_id": uuid | null }`) → 201

```jsonc
{
  "session_id": "uuid",
  "status": "created",
  "provider": "pipeline",
  "conversation_id": "uuid | null",
  "ws_path": "/api/realtime/sessions/{session_id}/ws",
  "ticket": "rt_…",              // one-time, valid ≤ 60 s, only for this session; never logged
  "ticket_expires_at": "iso",
  "expires_at": "iso",           // session TTL (REALTIME_VOICE_SESSION_TTL_SECONDS)
  "max_duration_seconds": 600,
  "speech_mode": "voice",
  "capabilities": { … as above … }
}
```

`GET  /api/clones/{clone_id}/realtime/session/{session_id}` → `{ session_id, status, provider, conversation_id, started_at, ended_at, duration_seconds, error_code, expires_at }` (only the session's owner).
`POST /api/clones/{clone_id}/realtime/session/{session_id}/end` → same body, status `ended` (idempotent).

Checks before creating (in this order, each a distinct error): feature on (`REALTIME_VOICE_ENABLED`) and provider configured → clone access → clone active → voice on with consent (`voice_enabled`) → owner switch `realtime_voice_enabled` → rate limit (`REALTIME_VOICE_RATE_LIMIT_PER_MINUTE`) → concurrent sessions (`REALTIME_VOICE_MAX_CONCURRENT_SESSIONS`, older live sessions of the same user are NOT auto-ended: 409) → plan quota (`realtime_voice_sessions` limit key; 0/absent = unlimited).

## Public visitors (optional, off by default)

`POST /api/public/clones/{slug}/realtime/session` with header `X-Public-Session: <public chat token>` (the existing public chat session) → 201 same shape (no `conversation_id`).
`POST /api/public/clones/{slug}/realtime/session/{session_id}/end` (same header).
Requires `public_realtime_voice_enabled` + public chat + public voice; uses the public
pipeline (public documents only, no memories, public message limits) and public rate limits.

## Errors (HTTP and WebSocket)

Body: the platform's normal error JSON (`detail`, plus `code`). Codes:

| code | HTTP | meaning |
|---|---|---|
| `realtime_disabled` | 503 | REALTIME_VOICE_ENABLED is false |
| `provider_not_configured` | 503 | no usable provider (e.g. no STT) |
| `consent_missing` | 409 | voice off / no voice consent |
| `realtime_off` | 409 | owner switched real-time voice off (or public flag off) |
| `forbidden` | 403/404 | no access to the clone (normal clone rules) |
| `rate_limited` | 429 | too many sessions per minute |
| `too_many_sessions` | 409 | concurrent session limit |
| `quota_exceeded` | 402 | plan quota reached |
| `session_not_found` | 404 | unknown id or not yours |
| `session_expired` | 410 | TTL or max duration passed |
| `provider_unavailable` | 503 | STT/LLM/TTS failed (temporary) |
| `signaling_failed` | — (WS close 4400) | bad ticket / bad message |

## WebSocket `GET {API_URL}{ws_path}?ticket=…`

* The `Origin` header must be an allowed origin (`REALTIME_VOICE_ALLOWED_ORIGINS`, else the CORS origins). Bad origin/ticket → close **4403**; expired → **4410**; not found → **4404**.
* The ticket is consumed on first use. One socket per session.
* Session ends on: client `end`, socket close, max duration (server sends `ended` with `reason: "max_duration"`), TTL.

Client → server

| frame | meaning |
|---|---|
| text `{"type":"hello"}` | first message; server answers `ready` |
| binary | one complete user utterance (audio/webm or audio/wav, ≤ `max_utterance_bytes`), cut by the browser's voice-activity detection. Starts a turn. |
| text `{"type":"text","text":"…"}` | typed message instead of speech. Starts a turn. |
| text `{"type":"interrupt"}` | stop the current answer now (cancel LLM + TTS); server answers `interrupted` |
| text `{"type":"speech_mode","mode":"voice"|"browser"}` | switch for the next turns |
| text `{"type":"end"}` | end the session |
| text `{"type":"ping"}` | keep-alive → `pong` |

A new utterance/text while a turn is running interrupts it first (barge-in).

Server → client (all text JSON, except audio payloads)

| message | meaning |
|---|---|
| `{"type":"ready","session_id","conversation_id","speech_mode","max_duration_seconds"}` | connected |
| `{"type":"state","state":"listening"|"thinking"|"speaking"}` | conversation state |
| `{"type":"transcript","turn":n,"text","language"}` | what the user said (after STT) |
| `{"type":"answer_delta","turn":n,"text"}` | streamed answer text |
| `{"type":"answer","turn":n,"text","message_id"|null}` | full answer (saved in the conversation) |
| `{"type":"audio","turn":n,"seq":k,"mime":"audio/mpeg"}` followed by **one binary frame** with that audio | one spoken sentence (speech mode `voice` only) |
| `{"type":"turn_done","turn":n}` | all audio for the turn sent |
| `{"type":"interrupted","turn":n}` | turn cancelled; drop any audio of turn ≤ n |
| `{"type":"error","code","message","turn"?:n,"fatal":bool}` | safe message (no internals) |
| `{"type":"ended","reason":"client"|"max_duration"|"expired"|"error"}` | then the server closes (1000) |
| `{"type":"pong"}` | |

`turn` numbers increase per session; the browser ignores audio for turns it has
interrupted. Only the answer of the current turn is saved; an interrupted answer is
saved with the text produced so far only if any text was produced (marked in metadata).

## Data

Migration `0021_realtime_voice`:
* `clone_profiles.realtime_voice_enabled` bool default true, `public_realtime_voice_enabled` bool default false, `realtime_speech_mode` varchar(16) default `'voice'`.
* table `realtime_voice_sessions`: id, clone_id, owner_id (nullable; the user), visitor_key (nullable; hashed public visitor), conversation_id nullable, provider, status (`created|connecting|connected|ended|failed|expired`), is_public, created_at, started_at, ended_at, expires_at, duration_seconds, turns, error_code, metadata JSON (safe values only), ticket_hash (sha256 of the ticket; never the ticket).

No raw audio or transcripts are stored by this feature (the conversation messages are stored exactly as in normal chat). `REALTIME_VOICE_AUDIO_RETENTION_ENABLED` exists and must stay false: retention is not implemented.

## Usage, billing, analytics

* `monitoring.usage("REALTIME_VOICE_SESSION", …, duration_ms=…)` at the end; per-turn STT/TTS usage is recorded by the existing voice services.
* analytics `record_event`: `realtime_voice_session_started`, `realtime_voice_session_ended` (duration, turns, reason), `realtime_voice_connection_failed`, `realtime_voice_provider_error` (category only).
* Plan limit key `realtime_voice_sessions` (sessions per billing month).

## Implementation notes (backend, as built)

* Error body: `{"detail": "<safe message>", "code": "<code>"}` (top-level `code`). Request-body
  validation errors keep the platform's normal format and status (400), e.g. an unknown `speech_mode`.
* Extra codes: `invalid_audio` (unreadable/empty/too large utterance, or STT found no speech),
  `invalid_message` (blank/too long text, unknown message type, bad `speech_mode`),
  `invalid_settings` (422, public switch without public chat + public voice). WebSocket turn errors
  are always `fatal: false`; only malformed JSON is fatal (`signaling_failed`, then close 4400).
* A public visitor whose public chat session has no messages left gets `quota_exceeded` (HTTP-like 429 in the WS error).
* Closing codes: maintenance mode → 1013 before accept. Session ended through the API while
  connected → `{"type":"ended","reason":"client"}` then close 1000.
* An interrupted answer that already produced text is saved as-is (no metadata marker: messages
  have no metadata column). An interrupted answer with no text is not saved.
* `GET /api/public/clones/{slug}` (`PublicClone`) has `realtime_voice_available`: feature on, provider
  configured, public chat on, public voice available, and `public_realtime_voice_enabled`.
* `/api/mobile/config` → `voice.realtime_voice` (bool).
* Per-turn access is re-checked (clone access, voice consent, public switches); the public
  pipeline (`public_rag_pipeline.retrieve_public_context` + public prompt) is used for visitors.
