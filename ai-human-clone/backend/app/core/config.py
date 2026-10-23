from functools import lru_cache
from typing import Annotated

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

APP_VERSION = "0.10.0"


class Settings(BaseSettings):
    """Application settings loaded from environment variables (and an optional .env file)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Clone Me API"
    # "production" turns on the startup checks in app/core/production.py.
    environment: str = "development"
    log_level: str = "INFO"
    # "text" (readable) or "json" (one JSON object per line, for log collectors).
    log_format: str = "text"
    # /docs, /redoc and /openapi.json. Unset: on in development, off in production.
    api_docs_enabled: bool | None = None
    # Comma-separated Host header allowlist (e.g. api.example.com). Empty: no check.
    allowed_hosts: Annotated[list[str], NoDecode] = Field(default_factory=list)
    # `python -m app.db.migrate` (the container start) skips migrations when false,
    # so a release can run them once, separately.
    run_migrations_on_start: bool = True

    # Comma-separated list of origins allowed to call the API from a browser.
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["http://localhost:3007"])

    database_url: str = "postgresql+psycopg://clone:clone@localhost:5432/ai_clone"
    # Connection pool per backend process (PostgreSQL). Total connections =
    # processes x (DB_POOL_SIZE + DB_MAX_OVERFLOW); keep it under max_connections.
    db_pool_size: int = Field(default=5, ge=1, le=100)
    db_max_overflow: int = Field(default=10, ge=0, le=100)
    db_pool_timeout_seconds: float = Field(default=30.0, gt=0)
    db_pool_recycle_seconds: int = Field(default=1800, ge=-1)
    # Server-side limit for one SQL statement (PostgreSQL); 0 turns it off.
    db_statement_timeout_ms: int = Field(default=30000, ge=0)

    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = None
    qdrant_collection: str = "clone_memories"

    # "auto" picks the first provider with a key: Claude, then Gemini, else demo mode.
    llm_provider: str = "auto"
    anthropic_api_key: str | None = None
    claude_model: str = "claude-opus-5-5"
    claude_max_tokens: int = 16000
    claude_effort: str = "medium"

    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.8-flash"
    # Used on the last retry when the main model is overloaded. Empty disables it.
    gemini_fallback_model: str = "gemini-3.5-flash-lite"
    gemini_max_tokens: int = 8192
    # minimal | low | medium | high
    gemini_thinking_level: str = "low"

    # Authentication. JWT_SECRET_KEY must be set outside development; see security.py.
    jwt_secret_key: str | None = None
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    auth_cookie_name: str = "access_token"
    # Secure cookies are only sent over HTTPS: keep False for local http://localhost.
    cookie_secure: bool = False
    cookie_samesite: str = "lax"
    frontend_url: str = "http://localhost:3007"

    # Embeddings are separate from the LLM. "local" runs a sentence-transformers
    # model on the CPU (ONNX via fastembed): no API key, no per-call cost. The
    # default is multilingual so Urdu / Roman Urdu content is searchable too.
    embedding_provider: str = "local"
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    embedding_cache_dir: str = "/app/.cache/fastembed"

    # Knowledge uploads. MAX_UPLOAD_MB is the older name of MAX_UPLOAD_SIZE_MB.
    max_upload_size_mb: int = Field(default=10, validation_alias=AliasChoices("MAX_UPLOAD_SIZE_MB", "MAX_UPLOAD_MB"))
    # Where uploaded files are stored (a Docker volume in compose).
    upload_dir: str = "/app/storage"
    # Extraction limits, so one huge or malformed file can't exhaust memory.
    max_extracted_characters: int = 500_000
    max_pdf_pages: int = 500
    manual_knowledge_max_characters: int = 50_000

    # Chunking (characters). Changing these affects documents indexed afterwards;
    # reindex older documents to apply them.
    chunk_size: int = 1000
    chunk_overlap: int = 150

    # Semantic search ("Test AI Memory")
    max_search_top_k: int = 20
    # Cosine similarity below this counts as "not relevant" and is dropped.
    min_similarity_score: float = 0.15

    # Chat / RAG. RAG_SCORE_THRESHOLD is the minimum cosine similarity for a chunk
    # to be given to the LLM; 0.15 was measured on the default embedding model
    # (0.35 drops real matches such as "hobbies" at ~0.20). See README.
    rag_top_k: int = Field(default=5, validation_alias=AliasChoices("RAG_TOP_K", "RETRIEVAL_TOP_K"))
    rag_score_threshold: float = 0.15
    rag_max_context_chars: int = 12_000
    max_conversation_messages: int = Field(
        default=10, validation_alias=AliasChoices("MAX_CONVERSATION_MESSAGES", "CHAT_HISTORY_LIMIT")
    )
    max_chat_message_length: int = 4000
    # Simple per-user abuse guard (in-process; one backend instance).
    chat_rate_limit_per_minute: int = 20
    # Per LLM HTTP request, and for a whole answer including provider retries.
    llm_timeout_seconds: float = 60.0
    chat_response_deadline_seconds: float = 90.0

    # Long-term memory. Approved memories live in their own Qdrant collection,
    # separate from document chunks (QDRANT_COLLECTION). The 0.25 threshold was
    # measured like RAG_SCORE_THRESHOLD: at 0.40, "What am I learning?" (0.34)
    # missed "The user is learning Python". See README.
    qdrant_memory_collection: str = "clone_long_term_memories"
    memory_top_k: int = 5
    memory_score_threshold: float = 0.25
    memory_max_context_chars: int = 5000
    memory_max_length: int = 1000
    # Cosine similarity at or above which two memories count as the same fact.
    memory_duplicate_threshold: float = 0.85
    # What one extraction request may send to the LLM, and keep.
    memory_extraction_max_messages: int = 40
    memory_extraction_max_chars: int = 20_000
    memory_extraction_max_candidates: int = 10

    # Voice. "auto" uses Gemini when a key is available (STT_API_KEY/TTS_API_KEY,
    # else GEMINI_API_KEY); "none" turns the feature off. See app/voice/factory.py.
    stt_provider: str = "auto"
    stt_api_key: str | None = None
    stt_model: str = "gemini-3.5-flash-lite"
    # Comma-separated models tried in order when the one before is busy or out of
    # quota. Free-tier quotas are per model (TTS models allow only ~10 requests a day
    # each), so every extra model adds capacity.
    stt_fallback_models: str = "gemini-3.1-flash-lite,gemini-2.5-flash-lite"
    tts_provider: str = "auto"
    tts_api_key: str | None = None
    tts_model: str = "gemini-3.8-flash-lite-tts"
    tts_fallback_models: str = Field(
        default="gemini-3.8-flash-tts,gemini-3.1-flash-tts-preview",
        validation_alias=AliasChoices("TTS_FALLBACK_MODELS", "TTS_FALLBACK_MODEL"),
    )
    # Default voice when a clone hasn't picked one.
    tts_voice: str = "Kore"
    # Longest answer read aloud; longer answers are cut at a sentence end.
    tts_max_characters: int = 2500
    max_audio_size_mb: int = 10
    max_audio_duration_seconds: float = 60.0
    voice_timeout_seconds: float = 60.0
    voice_rate_limit_per_minute: int = 10
    # Personal voice clone (ElevenLabs Instant Voice Cloning). Without a key, cloning is off
    # and clones keep using the prebuilt voices. eleven_v3 speaks 70+ languages incl. Urdu;
    # eleven_flash_v2_5 is faster (good for live calls) but has fewer languages.
    elevenlabs_api_key: str | None = None
    elevenlabs_model: str = "eleven_v3"
    elevenlabs_api_url: str = "https://api.elevenlabs.io"
    # Recording limits for building a voice clone (total length of the samples).
    voice_clone_min_seconds: float = 30.0
    voice_clone_max_seconds: float = 300.0
    voice_clone_max_files: int = 5
    # Which service clones voices: "auto" (ElevenLabs if ELEVENLABS_API_KEY is set, else the
    # local service if LOCAL_VOICE_CLONE_URL is set, else none), "elevenlabs", "local" or "none".
    voice_clone_provider: str = "auto"
    # Free self-hosted voice cloning (Chatterbox Multilingual, docker compose profile
    # "voice-clone"), e.g. http://voice-clone:8100. CPU speech is slow: hence the long timeout.
    local_voice_clone_url: str | None = None
    # Used when LOCAL_VOICE_CLONE_URL (e.g. a Google Colab GPU) is off: the laptop service.
    local_voice_clone_fallback_url: str | None = None
    voice_clone_service_token: str | None = None
    local_voice_clone_timeout_seconds: float = 300.0
    # Before the local voice speaks Roman Urdu or Urdu script, Gemini rewrites it in
    # Devanagari (it knows the words; the rule-based fallback only guesses spellings).
    voice_llm_transliteration: bool = True
    voice_transliteration_model: str = "gemini-3.1-flash-lite"
    voice_transliteration_timeout_seconds: float = 15.0
    # Generated speech lives in {upload_dir}/voice and is deleted after this many hours.
    voice_audio_retention_hours: float = 24.0

    # Avatar (talking-avatar videos). AVATAR_ENABLED=false turns the feature off.
    # LIPSYNC_PROVIDER: "local" (CPU, built in) or "http" (a lip-sync server such
    # as Wav2Lip/SadTalker/MuseTalk behind LIPSYNC_API_URL). See app/avatar/.
    avatar_feature_enabled: bool = Field(default=True, validation_alias=AliasChoices("AVATAR_ENABLED"))
    max_avatar_size_mb: int = 10
    lipsync_provider: str = "local"
    lipsync_api_url: str | None = None
    lipsync_api_key: str | None = None
    lipsync_timeout_seconds: float = 300.0
    # LIPSYNC_PROVIDER=fal: photo-realistic videos from a cloud model on fal.ai (paid per
    # second of video). The avatar photo and speech are sent to fal.ai.
    fal_api_key: str | None = Field(default=None, validation_alias=AliasChoices("FAL_API_KEY", "FAL_KEY"))
    # veed/fabric-1.0 (realistic, default), veed/fabric-1.0/fast, fal-ai/sadtalker, fal-ai/infinitalk
    fal_lipsync_model: str = "veed/fabric-1.0"
    fal_lipsync_resolution: str = "480p"  # 480p or 720p (720p costs about twice as much)

    # Live video call (Simli): the avatar is streamed in real time over WebRTC, idles
    # naturally (blinks, small head motion) while listening and lip-syncs the clone's
    # voice. Without SIMLI_API_KEY the video call is off. The avatar photo is sent to
    # Simli once to create the live face.
    simli_api_key: str | None = None
    simli_api_url: str = "https://api.simli.ai"
    live_call_max_minutes: int = 10
    live_call_max_idle_seconds: int = 120
    live_call_rate_limit_per_minute: int = 3
    max_video_duration_seconds: float = 60.0
    video_retention_hours: float = 24.0
    avatar_video_rate_limit_per_minute: int = 3
    # Videos rendered at the same time (CPU-bound); more wait in the queue.
    avatar_video_workers: int = 1
    avatar_video_fps: int = 25

    # Public clones (/c/{slug}): visitors without an account. Only content the
    # owner marked public is used; everything below limits cost and abuse.
    public_session_ttl_hours: float = 24.0
    max_public_messages_per_session: int = 50
    max_public_message_length: int = 4000
    public_chat_rate_limit_per_minute: int = 10
    public_voice_rate_limit_per_minute: int = 5
    public_avatar_rate_limit_per_minute: int = 2
    # New visitor sessions per client address per minute (stops session-hopping).
    public_session_rate_limit_per_minute: int = 10
    # Phase 18 marketplace: browsing requests per client address per minute, and reports
    # per reporter (user, or client address for visitors) per hour.
    marketplace_rate_limit_per_minute: int = 120
    marketplace_reports_per_hour: int = 5
    public_max_output_tokens: int = 1000
    # Model for public chat when the provider is Claude; empty = CLAUDE_MODEL.
    public_claude_model: str = ""
    public_rag_top_k: int = 5
    public_rag_max_context_chars: int = 8000
    # Optional anti-abuse challenge, checked when a visitor session starts. Any
    # "siteverify"-style service works (Turnstile, hCaptcha, reCAPTCHA): POST
    # secret + response to PUBLIC_CAPTCHA_VERIFY_URL, expect {"success": true}.
    public_captcha_enabled: bool = False
    public_captcha_verify_url: str | None = None
    public_captcha_secret: str | None = None
    # Use X-Forwarded-For for visitor rate limits only behind a trusted reverse proxy.
    trust_proxy_headers: bool = False
    # Public site address used in share links (falls back to FRONTEND_URL).
    public_site_url: str | None = None

    # Administration and security monitoring.
    # An existing account with this email is made admin at startup while no admin exists
    # (or use the CLI: python -m app.cli create-admin).
    initial_admin_email: str | None = None
    login_rate_limit_per_minute: int = 5
    # After this many failed logins in a row the account waits LOGIN_LOCKOUT_MINUTES.
    login_max_failed_attempts: int = 10
    login_lockout_minutes: int = 15
    security_log_retention_days: int = 30
    usage_log_retention_days: int = 90
    error_log_retention_days: int = 30
    # Optional prices for cost estimates (per unit: estimated token for LLMs,
    # character for TTS, audio second for STT). Empty = show usage only.
    claude_input_cost_per_unit: float | None = None
    claude_output_cost_per_unit: float | None = None
    gemini_input_cost_per_unit: float | None = None
    gemini_output_cost_per_unit: float | None = None
    stt_cost_per_unit: float | None = None
    tts_cost_per_unit: float | None = None
    # Per second of avatar video from a paid lip-sync provider (e.g. fal: 0.08 at 480p).
    lipsync_cost_per_unit: float | None = None
    # Billing
    billing_enabled: bool = False
    billing_provider: str | None = None
    stripe_secret_key: str | None = None
    stripe_webhook_secret: str | None = None
    stripe_publishable_key: str | None = None
    billing_currency: str = "USD"
    billing_success_url: str | None = None
    billing_cancel_url: str | None = None
    analytics_retention_days: int = 90

    # AI agent (Phase 16): controlled multi-step tool use. Off unless AGENT_ENABLED=true,
    # and then still off per clone until its owner enables it. Hard caps per execution:
    agent_enabled: bool = False
    agent_max_steps: int = 8
    agent_max_tool_calls: int = 12
    agent_max_execution_time_seconds: int = 60
    agent_max_context_chars: int = 16000
    agent_max_tool_retries: int = 2
    agent_web_search_enabled: bool = False
    # Which registered web search provider to use (none ships by default, so web search stays off).
    agent_web_search_provider: str | None = None
    # Ask before any action with a medium or higher risk (and tools marked "confirm").
    agent_default_confirmation_required: bool = True

    # Developer platform (Phase 14): API keys, /api/v1 and webhooks.
    # Per API key; a plan's api_rate_limit_per_minute overrides the per-minute value.
    api_rate_limit_per_minute: int = 60
    api_rate_limit_per_hour: int = 1000
    # Requests allowed within any single second (short bursts).
    api_rate_limit_burst: int = 10
    api_max_key_expiry_days: int = 365
    # Browser origins allowed to call /api/v1 directly (comma-separated; no cookies are
    # sent to /api/v1). Empty = server-to-server only.
    api_allowed_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)
    webhook_delivery_enabled: bool = True
    webhook_max_retries: int = 5
    webhook_timeout_seconds: float = 10.0
    # Failed delivery attempts in a row after which an endpoint is switched off (0 = never).
    webhook_auto_disable_after: int = 20
    # Base URL used in the developer docs and examples (default: the API's own address).
    public_api_url: str | None = None

    # Per minute of live video call (Simli: about 0.009-0.01).
    live_call_cost_per_unit: float | None = None

    # Phase 17: real-time voice conversations (app/realtime_voice). Off until enabled.
    realtime_voice_enabled: bool = False
    # "pipeline": WebSocket + this platform's own STT, clone chat pipeline and TTS.
    realtime_voice_provider: str = "pipeline"
    realtime_voice_session_ttl_seconds: int = 600
    realtime_voice_max_duration_seconds: int = 600
    realtime_voice_max_concurrent_sessions: int = 1
    realtime_voice_rate_limit_per_minute: int = 5
    # Origins allowed to open the WebSocket; empty = the CORS origins.
    realtime_voice_allowed_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)
    # Not implemented: real-time audio is never stored. Setting it true only logs a warning.
    realtime_voice_audio_retention_enabled: bool = False
    realtime_voice_max_utterance_bytes: int = 2_000_000
    realtime_voice_max_utterance_seconds: float = 30.0
    realtime_voice_ticket_ttl_seconds: int = 60

    @field_validator("cors_origins", "api_allowed_origins", "realtime_voice_allowed_origins", "allowed_hosts", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator(
        "anthropic_api_key",
        "gemini_api_key",
        "qdrant_api_key",
        "jwt_secret_key",
        "api_docs_enabled",
        "stt_api_key",
        "tts_api_key",
        "lipsync_api_key",
        "lipsync_api_url",
        "elevenlabs_api_key",
        "local_voice_clone_url",
        "voice_clone_service_token",
        "fal_api_key",
        "simli_api_key",
        "live_call_cost_per_unit",
        "lipsync_cost_per_unit",
        "public_captcha_verify_url",
        "public_captcha_secret",
        "public_site_url",
        "public_api_url",
        "agent_web_search_provider",
        "initial_admin_email",
        "claude_input_cost_per_unit",
        "claude_output_cost_per_unit",
        "gemini_input_cost_per_unit",
        "gemini_output_cost_per_unit",
        "stt_cost_per_unit",
        "tts_cost_per_unit",
        mode="before",
    )
    @classmethod
    def _empty_to_none(cls, value: object) -> object:
        # Docker Compose passes unset variables as empty strings.
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("voice_clone_provider", mode="before")
    @classmethod
    def _voice_clone_provider(cls, value: object) -> object:
        value = (str(value).strip().lower() if value is not None else "") or "auto"
        if value not in ("auto", "elevenlabs", "local", "none"):
            raise ValueError("VOICE_CLONE_PROVIDER must be auto, elevenlabs, local or none")
        return value

    @property
    def is_production(self) -> bool:
        return self.environment.strip().lower() == "production"

    @property
    def docs_enabled(self) -> bool:
        return self.api_docs_enabled if self.api_docs_enabled is not None else not self.is_production

    @property
    def allowed_origins(self) -> list[str]:
        """CORS origins: CORS_ORIGINS plus FRONTEND_URL. Never "*", since cookies are sent."""
        origins = [*self.cors_origins, self.frontend_url.rstrip("/")]
        return [origin for origin in dict.fromkeys(origins) if origin and origin != "*"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
