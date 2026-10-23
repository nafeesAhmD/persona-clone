# Environment variables

Where values come from:
* **Backend** — `backend/app/core/config.py` (pydantic settings): environment variables, or the
  `.env` file in development (`.env.production` via `docker-compose.prod.yml` in production).
  Names are case-insensitive; lists are comma-separated.
* **Frontend** — only `NEXT_PUBLIC_API_URL` reaches the browser (baked in at build time).
  No API key may ever be put in a `NEXT_PUBLIC_*` variable.
* **Compose** — variables used by `docker-compose.yml` / `docker-compose.prod.yml` themselves.

Never commit `.env` or `.env.production` (both are git-ignored). Examples with placeholders:
`.env.example` (development) and `.env.production.example` (production).

## Required in production

With `ENVIRONMENT=production` the backend **refuses to start** (`app/core/production.py`) and
names every problem (never its value) unless:

| Variable | Rule |
|---|---|
| `JWT_SECRET_KEY` | set, ≥ 32 characters, not an example placeholder |
| `COOKIE_SECURE` | `true` (cookies only over HTTPS) |
| `CORS_ORIGINS` | not empty, no `*`, every origin `https://` and not localhost |
| `FRONTEND_URL` | `https://`, not localhost |
| `PUBLIC_SITE_URL`, `PUBLIC_API_URL` | if set: `https://`, not localhost |
| `DATABASE_URL` | not the development user/password (`clone`/`clone`) |
| `QDRANT_API_KEY` | set (Qdrant must not accept anyone on its network) |
| `API_DOCS_ENABLED` | false or unset (`/docs`, `/redoc`, `/openapi.json` off) |
| `REALTIME_VOICE_AUDIO_RETENTION_ENABLED` | false (not implemented) |

Also recommended: `ALLOWED_HOSTS=<your domain>,backend,localhost,127.0.0.1` (the internal names are
needed by the container healthcheck and the frontend's server-side API calls), `TRUST_PROXY_HEADERS=true` behind Caddy,
`LOG_FORMAT=json`, and at least one LLM key (`GEMINI_API_KEY` or `ANTHROPIC_API_KEY`).
More than one backend process (`WEB_CONCURRENCY>1`) only logs a warning — see SCALING_GUIDE.md.

## Compose (production: `docker-compose.prod.yml`)

| Variable | Purpose | Secret |
|---|---|---|
| `DOMAIN` | Site domain; Caddy gets its HTTPS certificate for it | |
| `ACME_EMAIL` | Contact for Let's Encrypt | |
| `PUBLIC_API_URL` | Public API origin, baked into the frontend build (`NEXT_PUBLIC_API_URL`) | |
| `ENV_FILE` | Path of the env file loaded into backend/migrate (default `.env.production`) | |
| `IMAGE_TAG` | Tag for the built images (default `latest`); use a release tag to roll back | |
| `POSTGRES_DB` | Application database name | |
| `POSTGRES_SUPERUSER`, `POSTGRES_SUPERUSER_PASSWORD` | PostgreSQL superuser — administration and backups only | password: yes |
| `POSTGRES_APP_USER`, `POSTGRES_APP_PASSWORD` | Restricted login the app uses (created by `deploy/postgres/init-app-user.sh` on first start) | password: yes |
| `POSTGRES_MAX_CONNECTIONS`, `POSTGRES_SHARED_BUFFERS` | PostgreSQL server limits (default 100, 256MB) | |
| `QDRANT_API_KEY` | Qdrant API key (also passed to the backend) | yes |
| `QDRANT_VERSION` | Qdrant image tag (default `latest`; pin it) | |
| `VOICE_CLONE_SERVICE_TOKEN` | Token between backend and the optional voice-clone service | yes |
| `BACKEND_MEM_LIMIT`, `FRONTEND_MEM_LIMIT`, `POSTGRES_MEM_LIMIT`, `QDRANT_MEM_LIMIT` | Container memory limits | |
| `FORWARDED_ALLOW_IPS` | Proxies uvicorn trusts for `X-Forwarded-*` (entrypoint; default `*`, only Caddy can reach the backend) | |
| `RUN_MIGRATIONS_ON_START` | Set per service by the prod compose: `true` for `migrate`, `false` for `backend` | |

Development (`docker-compose.yml`): `POSTGRES_USER`/`POSTGRES_PASSWORD`/`POSTGRES_DB`
(default `clone`/`clone`/`ai_clone`, development only), `POSTGRES_PORT`, `QDRANT_PORT` (bound to
127.0.0.1), `BACKEND_PORT`, `FRONTEND_PORT`, `NEXT_PUBLIC_API_URL`, `SYNTH_TIMEOUT_SECONDS`.

## Frontend

| Variable | Where | Purpose |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | build argument (public) | API origin used by browsers |
| `API_INTERNAL_URL` | runtime (server only) | API address for server-side rendering inside the Docker network |
| `NEXT_PUBLIC_BUILD_ID` | build (public, optional) | Build id for PWA update detection (defaults to the build time) |

## Voice-clone service (`voice-clone/`)

`VOICE_CLONE_SERVICE_TOKEN` (secret), `VOICE_CLONE_ENGINE` (`chatterbox`|`omnivoice`),
`VOICE_CLONE_DEVICE` (`auto`|`cpu`|`cuda`), `OMNIVOICE_STEPS`, `VOICE_DATA_DIR`,
`SYNTH_TIMEOUT_SECONDS`, `MODEL_WAIT_SECONDS`, `MAX_UPLOAD_MB`, `MAX_QUEUED_SYNTHESES`,
`TORCH_NUM_THREADS`, `HF_HOME`, `HF_HUB_DISABLE_XET`.

## Backend: every setting

Generated from `backend/app/core/config.py` (the note is the comment above the field, when
there is one; the file is the authority). "Secret" = keep it out of logs, Git and the frontend.

| Variable | Default | Secret | Note |
|---|---|---|---|
| `APP_NAME` | `"AI Human Clone API"` |  |  |
| `ENVIRONMENT` | `"development"` |  | "production" turns on the startup checks in app/core/production.py. |
| `LOG_LEVEL` | `"INFO"` |  |  |
| `LOG_FORMAT` | `"text"` |  | "text" (readable) or "json" (one JSON object per line, for log collectors). |
| `API_DOCS_ENABLED` | `None` |  | /docs, /redoc and /openapi.json. Unset: on in development, off in production. |
| `ALLOWED_HOSTS` | `(empty list)` |  | Comma-separated Host header allowlist (e.g. api.example.com). Empty: no check. |
| `RUN_MIGRATIONS_ON_START` | `True` |  | `python -m app.db.migrate` (the container start) skips migrations when false, |
| `CORS_ORIGINS` | `http://localhost:3007` |  | Comma-separated list of origins allowed to call the API from a browser. |
| `DATABASE_URL` | `"postgresql+psycopg://clone:clone@localhost:5432/ai_clone"` | yes |  |
| `DB_POOL_SIZE` | `5` |  | Connection pool per backend process (PostgreSQL). Total connections = |
| `DB_MAX_OVERFLOW` | `10` |  |  |
| `DB_POOL_TIMEOUT_SECONDS` | `30.0` |  |  |
| `DB_POOL_RECYCLE_SECONDS` | `1800` |  |  |
| `DB_STATEMENT_TIMEOUT_MS` | `30000` |  | Server-side limit for one SQL statement (PostgreSQL); 0 turns it off. |
| `QDRANT_URL` | `"http://localhost:6333"` |  |  |
| `QDRANT_API_KEY` | `None` | yes |  |
| `QDRANT_COLLECTION` | `"clone_memories"` |  |  |
| `LLM_PROVIDER` | `"auto"` |  | "auto" picks the first provider with a key: Claude, then Gemini, else demo mode. |
| `ANTHROPIC_API_KEY` | `None` | yes |  |
| `CLAUDE_MODEL` | `"claude-opus-5-5"` |  |  |
| `CLAUDE_MAX_TOKENS` | `16000` |  |  |
| `CLAUDE_EFFORT` | `"medium"` |  |  |
| `GEMINI_API_KEY` | `None` | yes |  |
| `GEMINI_MODEL` | `"gemini-3.8-flash"` |  |  |
| `GEMINI_FALLBACK_MODEL` | `"gemini-3.5-flash-lite"` |  | Used on the last retry when the main model is overloaded. Empty disables it. |
| `GEMINI_MAX_TOKENS` | `8192` |  |  |
| `GEMINI_THINKING_LEVEL` | `"low"` |  | minimal / low / medium / high |
| `JWT_SECRET_KEY` | `None` | yes | Authentication. JWT_SECRET_KEY must be set outside development; see security.py. |
| `JWT_ALGORITHM` | `"HS256"` |  |  |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` |  |  |
| `AUTH_COOKIE_NAME` | `"access_token"` |  |  |
| `COOKIE_SECURE` | `False` |  | Secure cookies are only sent over HTTPS: keep False for local http://localhost. |
| `COOKIE_SAMESITE` | `"lax"` |  |  |
| `FRONTEND_URL` | `"http://localhost:3007"` |  |  |
| `EMBEDDING_PROVIDER` | `"local"` |  | Embeddings are separate from the LLM. "local" runs a sentence-transformers |
| `EMBEDDING_MODEL` | `"sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"` |  |  |
| `EMBEDDING_CACHE_DIR` | `"/app/.cache/fastembed"` |  |  |
| `MAX_UPLOAD_SIZE_MB` | `10` |  | Knowledge uploads. MAX_UPLOAD_MB is the older name of MAX_UPLOAD_SIZE_MB. |
| `UPLOAD_DIR` | `"/app/storage"` |  | Where uploaded files are stored (a Docker volume in compose). |
| `MAX_EXTRACTED_CHARACTERS` | `500_000` |  | Extraction limits, so one huge or malformed file can't exhaust memory. |
| `MAX_PDF_PAGES` | `500` |  |  |
| `MANUAL_KNOWLEDGE_MAX_CHARACTERS` | `50_000` |  |  |
| `CHUNK_SIZE` | `1000` |  | Chunking (characters). Changing these affects documents indexed afterwards; |
| `CHUNK_OVERLAP` | `150` |  |  |
| `MAX_SEARCH_TOP_K` | `20` |  | Semantic search ("Test AI Memory") |
| `MIN_SIMILARITY_SCORE` | `0.15` |  | Cosine similarity below this counts as "not relevant" and is dropped. |
| `RAG_TOP_K` | `5` |  | Chat / RAG. RAG_SCORE_THRESHOLD is the minimum cosine similarity for a chunk |
| `RAG_SCORE_THRESHOLD` | `0.15` |  |  |
| `RAG_MAX_CONTEXT_CHARS` | `12_000` |  |  |
| `MAX_CONVERSATION_MESSAGES` | `(see config.py)` |  |  |
| `MAX_CHAT_MESSAGE_LENGTH` | `4000` |  |  |
| `CHAT_RATE_LIMIT_PER_MINUTE` | `20` |  | Simple per-user abuse guard (in-process; one backend instance). |
| `LLM_TIMEOUT_SECONDS` | `60.0` |  | Per LLM HTTP request, and for a whole answer including provider retries. |
| `CHAT_RESPONSE_DEADLINE_SECONDS` | `90.0` |  |  |
| `QDRANT_MEMORY_COLLECTION` | `"clone_long_term_memories"` |  | Long-term memory. Approved memories live in their own Qdrant collection, |
| `MEMORY_TOP_K` | `5` |  |  |
| `MEMORY_SCORE_THRESHOLD` | `0.25` |  |  |
| `MEMORY_MAX_CONTEXT_CHARS` | `5000` |  |  |
| `MEMORY_MAX_LENGTH` | `1000` |  |  |
| `MEMORY_DUPLICATE_THRESHOLD` | `0.85` |  | Cosine similarity at or above which two memories count as the same fact. |
| `MEMORY_EXTRACTION_MAX_MESSAGES` | `40` |  | What one extraction request may send to the LLM, and keep. |
| `MEMORY_EXTRACTION_MAX_CHARS` | `20_000` |  |  |
| `MEMORY_EXTRACTION_MAX_CANDIDATES` | `10` |  |  |
| `STT_PROVIDER` | `"auto"` |  | Voice. "auto" uses Gemini when a key is available (STT_API_KEY/TTS_API_KEY, |
| `STT_API_KEY` | `None` | yes |  |
| `STT_MODEL` | `"gemini-3.5-flash-lite"` |  |  |
| `STT_FALLBACK_MODELS` | `"gemini-3.1-flash-lite,gemini-2.5-flash-lite"` |  | Comma-separated models tried in order when the one before is busy or out of |
| `TTS_PROVIDER` | `"auto"` |  |  |
| `TTS_API_KEY` | `None` | yes |  |
| `TTS_MODEL` | `"gemini-3.8-flash-lite-tts"` |  |  |
| `TTS_FALLBACK_MODELS` | `(see config.py)` |  |  |
| `TTS_VOICE` | `"Kore"` |  | Default voice when a clone hasn't picked one. |
| `TTS_MAX_CHARACTERS` | `2500` |  | Longest answer read aloud; longer answers are cut at a sentence end. |
| `MAX_AUDIO_SIZE_MB` | `10` |  |  |
| `MAX_AUDIO_DURATION_SECONDS` | `60.0` |  |  |
| `VOICE_TIMEOUT_SECONDS` | `60.0` |  |  |
| `VOICE_RATE_LIMIT_PER_MINUTE` | `10` |  |  |
| `ELEVENLABS_API_KEY` | `None` | yes | Personal voice clone (ElevenLabs Instant Voice Cloning). Without a key, cloning is off |
| `ELEVENLABS_MODEL` | `"eleven_v3"` |  |  |
| `ELEVENLABS_API_URL` | `"https://api.elevenlabs.io"` |  |  |
| `VOICE_CLONE_MIN_SECONDS` | `30.0` |  | Recording limits for building a voice clone (total length of the samples). |
| `VOICE_CLONE_MAX_SECONDS` | `300.0` |  |  |
| `VOICE_CLONE_MAX_FILES` | `5` |  |  |
| `VOICE_CLONE_PROVIDER` | `"auto"` |  | Which service clones voices: "auto" (ElevenLabs if ELEVENLABS_API_KEY is set, else the |
| `LOCAL_VOICE_CLONE_URL` | `None` |  | Free self-hosted voice cloning (Chatterbox Multilingual, docker compose profile |
| `LOCAL_VOICE_CLONE_FALLBACK_URL` | `None` |  | Used when LOCAL_VOICE_CLONE_URL (e.g. a Google Colab GPU) is off: the laptop service. |
| `VOICE_CLONE_SERVICE_TOKEN` | `None` | yes |  |
| `LOCAL_VOICE_CLONE_TIMEOUT_SECONDS` | `300.0` |  |  |
| `VOICE_LLM_TRANSLITERATION` | `True` |  | Before the local voice speaks Roman Urdu or Urdu script, Gemini rewrites it in |
| `VOICE_TRANSLITERATION_MODEL` | `"gemini-3.1-flash-lite"` |  |  |
| `VOICE_TRANSLITERATION_TIMEOUT_SECONDS` | `15.0` |  |  |
| `VOICE_AUDIO_RETENTION_HOURS` | `24.0` |  | Generated speech lives in {upload_dir}/voice and is deleted after this many hours. |
| `AVATAR_FEATURE_ENABLED` | `True` |  | Avatar (talking-avatar videos). AVATAR_ENABLED=false turns the feature off. |
| `MAX_AVATAR_SIZE_MB` | `10` |  |  |
| `LIPSYNC_PROVIDER` | `"local"` |  |  |
| `LIPSYNC_API_URL` | `None` |  |  |
| `LIPSYNC_API_KEY` | `None` | yes |  |
| `LIPSYNC_TIMEOUT_SECONDS` | `300.0` |  |  |
| `FAL_API_KEY` | `None` | yes | LIPSYNC_PROVIDER=fal: photo-realistic videos from a cloud model on fal.ai (paid per |
| `FAL_LIPSYNC_MODEL` | `"veed/fabric-1.0"` |  | veed/fabric-1.0 (realistic, default), veed/fabric-1.0/fast, fal-ai/sadtalker, fal-ai/infinitalk |
| `FAL_LIPSYNC_RESOLUTION` | `"480p"` |  |  |
| `SIMLI_API_KEY` | `None` | yes | Live video call (Simli): the avatar is streamed in real time over WebRTC, idles |
| `SIMLI_API_URL` | `"https://api.simli.ai"` |  |  |
| `LIVE_CALL_MAX_MINUTES` | `10` |  |  |
| `LIVE_CALL_MAX_IDLE_SECONDS` | `120` |  |  |
| `LIVE_CALL_RATE_LIMIT_PER_MINUTE` | `3` |  |  |
| `MAX_VIDEO_DURATION_SECONDS` | `60.0` |  |  |
| `VIDEO_RETENTION_HOURS` | `24.0` |  |  |
| `AVATAR_VIDEO_RATE_LIMIT_PER_MINUTE` | `3` |  |  |
| `AVATAR_VIDEO_WORKERS` | `1` |  | Videos rendered at the same time (CPU-bound); more wait in the queue. |
| `AVATAR_VIDEO_FPS` | `25` |  |  |
| `PUBLIC_SESSION_TTL_HOURS` | `24.0` |  | Public clones (/c/{slug}): visitors without an account. Only content the |
| `MAX_PUBLIC_MESSAGES_PER_SESSION` | `50` |  |  |
| `MAX_PUBLIC_MESSAGE_LENGTH` | `4000` |  |  |
| `PUBLIC_CHAT_RATE_LIMIT_PER_MINUTE` | `10` |  |  |
| `PUBLIC_VOICE_RATE_LIMIT_PER_MINUTE` | `5` |  |  |
| `PUBLIC_AVATAR_RATE_LIMIT_PER_MINUTE` | `2` |  |  |
| `PUBLIC_SESSION_RATE_LIMIT_PER_MINUTE` | `10` |  | New visitor sessions per client address per minute (stops session-hopping). |
| `MARKETPLACE_RATE_LIMIT_PER_MINUTE` | `120` |  | Phase 18 marketplace: browsing requests per client address per minute, and reports |
| `MARKETPLACE_REPORTS_PER_HOUR` | `5` |  |  |
| `PUBLIC_MAX_OUTPUT_TOKENS` | `1000` |  |  |
| `PUBLIC_CLAUDE_MODEL` | `""` |  | Model for public chat when the provider is Claude; empty = CLAUDE_MODEL. |
| `PUBLIC_RAG_TOP_K` | `5` |  |  |
| `PUBLIC_RAG_MAX_CONTEXT_CHARS` | `8000` |  |  |
| `PUBLIC_CAPTCHA_ENABLED` | `False` |  | Optional anti-abuse challenge, checked when a visitor session starts. Any |
| `PUBLIC_CAPTCHA_VERIFY_URL` | `None` |  |  |
| `PUBLIC_CAPTCHA_SECRET` | `None` | yes |  |
| `TRUST_PROXY_HEADERS` | `False` |  | Use X-Forwarded-For for visitor rate limits only behind a trusted reverse proxy. |
| `PUBLIC_SITE_URL` | `None` |  | Public site address used in share links (falls back to FRONTEND_URL). |
| `INITIAL_ADMIN_EMAIL` | `None` |  | Administration and security monitoring. |
| `LOGIN_RATE_LIMIT_PER_MINUTE` | `5` |  |  |
| `LOGIN_MAX_FAILED_ATTEMPTS` | `10` |  | After this many failed logins in a row the account waits LOGIN_LOCKOUT_MINUTES. |
| `LOGIN_LOCKOUT_MINUTES` | `15` |  |  |
| `SECURITY_LOG_RETENTION_DAYS` | `30` |  |  |
| `USAGE_LOG_RETENTION_DAYS` | `90` |  |  |
| `ERROR_LOG_RETENTION_DAYS` | `30` |  |  |
| `CLAUDE_INPUT_COST_PER_UNIT` | `None` |  | Optional prices for cost estimates (per unit: estimated token for LLMs, |
| `CLAUDE_OUTPUT_COST_PER_UNIT` | `None` |  |  |
| `GEMINI_INPUT_COST_PER_UNIT` | `None` |  |  |
| `GEMINI_OUTPUT_COST_PER_UNIT` | `None` |  |  |
| `STT_COST_PER_UNIT` | `None` |  |  |
| `TTS_COST_PER_UNIT` | `None` |  |  |
| `LIPSYNC_COST_PER_UNIT` | `None` |  | Per second of avatar video from a paid lip-sync provider (e.g. fal: 0.08 at 480p). |
| `BILLING_ENABLED` | `False` |  | Billing |
| `BILLING_PROVIDER` | `None` |  |  |
| `STRIPE_SECRET_KEY` | `None` | yes |  |
| `STRIPE_WEBHOOK_SECRET` | `None` | yes |  |
| `STRIPE_PUBLISHABLE_KEY` | `None` | yes |  |
| `BILLING_CURRENCY` | `"USD"` |  |  |
| `BILLING_SUCCESS_URL` | `None` |  |  |
| `BILLING_CANCEL_URL` | `None` |  |  |
| `ANALYTICS_RETENTION_DAYS` | `90` |  |  |
| `AGENT_ENABLED` | `False` |  | AI agent (Phase 16): controlled multi-step tool use. Off unless AGENT_ENABLED=true, |
| `AGENT_MAX_STEPS` | `8` |  |  |
| `AGENT_MAX_TOOL_CALLS` | `12` |  |  |
| `AGENT_MAX_EXECUTION_TIME_SECONDS` | `60` |  |  |
| `AGENT_MAX_CONTEXT_CHARS` | `16000` |  |  |
| `AGENT_MAX_TOOL_RETRIES` | `2` |  |  |
| `AGENT_WEB_SEARCH_ENABLED` | `False` |  |  |
| `AGENT_WEB_SEARCH_PROVIDER` | `None` |  | Which registered web search provider to use (none ships by default, so web search stays off). |
| `AGENT_DEFAULT_CONFIRMATION_REQUIRED` | `True` |  | Ask before any action with a medium or higher risk (and tools marked "confirm"). |
| `API_RATE_LIMIT_PER_MINUTE` | `60` |  | Developer platform (Phase 14): API keys, /api/v1 and webhooks. |
| `API_RATE_LIMIT_PER_HOUR` | `1000` |  |  |
| `API_RATE_LIMIT_BURST` | `10` |  | Requests allowed within any single second (short bursts). |
| `API_MAX_KEY_EXPIRY_DAYS` | `365` |  |  |
| `API_ALLOWED_ORIGINS` | `(empty list)` |  | Browser origins allowed to call /api/v1 directly (comma-separated; no cookies are |
| `WEBHOOK_DELIVERY_ENABLED` | `True` |  |  |
| `WEBHOOK_MAX_RETRIES` | `5` |  |  |
| `WEBHOOK_TIMEOUT_SECONDS` | `10.0` |  |  |
| `WEBHOOK_AUTO_DISABLE_AFTER` | `20` |  | Failed delivery attempts in a row after which an endpoint is switched off (0 = never). |
| `PUBLIC_API_URL` | `None` |  | Base URL used in the developer docs and examples (default: the API's own address). |
| `LIVE_CALL_COST_PER_UNIT` | `None` |  | Per minute of live video call (Simli: about 0.009-0.01). |
| `REALTIME_VOICE_ENABLED` | `False` |  | Phase 17: real-time voice conversations (app/realtime_voice). Off until enabled. |
| `REALTIME_VOICE_PROVIDER` | `"pipeline"` |  | "pipeline": WebSocket + this platform's own STT, clone chat pipeline and TTS. |
| `REALTIME_VOICE_SESSION_TTL_SECONDS` | `600` |  |  |
| `REALTIME_VOICE_MAX_DURATION_SECONDS` | `600` |  |  |
| `REALTIME_VOICE_MAX_CONCURRENT_SESSIONS` | `1` |  |  |
| `REALTIME_VOICE_RATE_LIMIT_PER_MINUTE` | `5` |  |  |
| `REALTIME_VOICE_ALLOWED_ORIGINS` | `(empty list)` |  | Origins allowed to open the WebSocket; empty = the CORS origins. |
| `REALTIME_VOICE_AUDIO_RETENTION_ENABLED` | `False` |  | Not implemented: real-time audio is never stored. Setting it true only logs a warning. |
| `REALTIME_VOICE_MAX_UTTERANCE_BYTES` | `2_000_000` |  |  |
| `REALTIME_VOICE_MAX_UTTERANCE_SECONDS` | `30.0` |  |  |
| `REALTIME_VOICE_TICKET_TTL_SECONDS` | `60` |  |  |
