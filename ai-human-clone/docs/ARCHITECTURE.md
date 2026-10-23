# Architecture

What the code in this repository actually does (checked against the source, October 2026).
Deployment details: [PRODUCTION_DEPLOYMENT.md](PRODUCTION_DEPLOYMENT.md) · scaling limits:
[SCALING_GUIDE.md](SCALING_GUIDE.md) · endpoints: [API.md](API.md).

## Components

```
Browser (Next.js 16 app, PWA)
   │  HTTPS: REST + SSE (chat streaming) + one WebSocket (real-time voice)
   ▼
[Caddy reverse proxy — production compose only: TLS, /api → backend, rest → frontend]
   │
   ├── frontend/  Next.js (standalone server, port 3000). Server-side renders public /c/[slug]
   │              pages by calling the backend inside the Docker network (API_INTERNAL_URL).
   └── backend/   FastAPI (one uvicorn process, port 8000)
         ├── PostgreSQL 16   users, clones, documents, conversations, memories, billing, orgs,
         │                   API keys, webhooks, analytics, agent runs, realtime sessions,
         │                   marketplace (Alembic migrations 0001 → 0022)
         ├── Qdrant          vectors: `clone_memories` (document chunks),
         │                   `clone_long_term_memories` (approved memories); payload-indexed
         │                   by clone_id, document_id, user_id, owner_id, memory_id, status
         ├── local disk      /app/storage (documents, avatars, generated audio/video) — Docker volumes
         └── voice-clone/    optional service (compose profile `voice-clone`): self-hosted voice
                             cloning, Chatterbox (MIT, CPU) or OmniVoice (GPU, non-commercial)
External providers (keys in .env only): Anthropic Claude and/or Google Gemini (LLM, speech-to-
text, text-to-speech), ElevenLabs (optional cloned voice), Simli (optional live avatar),
fal / HTTP lip-sync (optional avatar videos). Without an LLM key chat runs in a "demo" mode.
```

The embedding model (`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`) runs inside
the backend process (downloaded once into the `model_cache` volume).

## Request flows

**Auth.** Register/login set an HttpOnly session cookie (JWT signed with `JWT_SECRET_KEY`);
`/api/auth/me` renews it. Ownership and organization roles are checked in each service
(`clone_service.get_managed_clone` / `get_chat_clone`, org permission helpers); admin routes use
a central admin dependency. The developer API (`/api/v1`) uses `Authorization: Bearer ahc_live_…`
keys stored as HMAC hashes, with scopes.

**Knowledge.** Upload (`POST /api/clones/{id}/documents`) → validation (type, size) → text
extraction → chunking (`text_chunker`) → embeddings → Qdrant upsert. This runs **inside the upload
request** (in a worker thread), not in a queue, so large files make the request slow.

**Chat (RAG).** `chat_service.prepare_stream` saves the user turn, then `_retrieve` searches the
clone's chunks and approved long-term memories in Qdrant (always filtered by clone),
`clone_prompt` builds the system prompt (personality, rules, "you are an AI representation"),
and `rag_pipeline.stream_clone_response` streams the answer from Claude or Gemini (fallback model
on overload) as server-sent events; sources are returned with the answer. Public visitors go
through `public_rag_pipeline`: public documents only, no private memories, per-session message
limits.

**Memory.** `memory_extractor` proposes memories from conversations; only memories the owner
approves are embedded into `clone_long_term_memories` and used in answers.

**Voice.** Speech-to-text (Gemini) → normal chat turn → text-to-speech with the clone's voice:
Gemini voices, an ElevenLabs cloned voice, or the self-hosted `voice-clone` service
(`app/voice/routing.py` picks; `pronounce.py` asks Gemini to spell Urdu/Roman Urdu for the speech
model). Generated audio is stored under `/app/storage/voice` and deleted after
`VOICE_AUDIO_RETENTION_HOURS`. Voice needs owner consent (`voice_consent_given`).

**Real-time voice (Phase 17).** `POST …/realtime/session` (all checks) returns a one-time ticket;
the browser opens `wss://…/api/realtime/sessions/{id}/ws?ticket=…`; each spoken utterance runs
STT → the same chat pipeline → sentence-by-sentence speech over the socket; interrupt cancels the
turn task. Provider: `pipeline` (no WebRTC media server).

**Avatar.** Photo (with consent) → talking-head video jobs through a lip-sync provider
(`app/avatar/jobs.py`, background thread pool) or a live Simli call.

**Agent (Phase 16).** Planner (LLM, JSON) → tool registry with per-clone permissions
(calculator, date/time, clone info, knowledge search, memory search, conversation context,
optional web search) → executor with step/time limits and loop detection; risky steps wait for a
single-use confirmation. No shell, code execution, filesystem or arbitrary HTTP tools.

**Marketplace (Phase 18).** Owner opt-in + eligibility predicate (`app/marketplace/queries.py`);
PostgreSQL full-text search over public profile fields only; favorites, reports, admin moderation.

**Developer platform (Phase 14).** API keys, `/api/v1` endpoints, webhooks signed with HMAC and
delivered by a background worker with SSRF protection.

## Background work (all inside the backend process)

Started in `app/main.py` lifespan, stopped on shutdown with bounded waits:

| Worker | What |
|---|---|
| embedding warm-up thread | loads the embedding model at start |
| webhook delivery worker | sends/retries webhook events |
| agent runner thread pool | runs agent executions; interrupted runs are marked failed on restart |
| avatar job thread pool | lip-sync video jobs; interrupted jobs recovered on restart |
| voice audio cleanup task | deletes expired generated audio |
| monitoring writer | writes usage/security/error rows off the request path |

There is no external queue (no Redis/Celery). Document indexing runs in the request.

## Single-process constraint

Rate limits, real-time voice sessions/tickets, marketplace view de-duplication and the job
runners above live in process memory. Run **one** backend process (the default entrypoint starts
a single uvicorn worker; `WEB_CONCURRENCY>1` only logs a warning). Running several instances needs
shared state (e.g. Redis), sticky WebSocket routing and an external job queue — see
[SCALING_GUIDE.md](SCALING_GUIDE.md).

## Storage and data lifecycle

* PostgreSQL and Qdrant: Docker volumes (`postgres_data`, `qdrant_data`).
* Files: `/app/storage` volume (`document_storage`, `voice_audio`); no object-storage adapter yet.
* Generated speech: deleted after `VOICE_AUDIO_RETENTION_HOURS`. Real-time voice stores no audio.
* Backups: `scripts/backup.sh` / `scripts/restore.sh` ([BACKUP_AND_RESTORE.md](BACKUP_AND_RESTORE.md)).
