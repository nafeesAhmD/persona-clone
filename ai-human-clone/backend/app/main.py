import asyncio
import contextlib
import logging
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.agent import runner as agent_runner
from app.ai import LLMError
from app.ai.embedding_service import EmbeddingError, get_embedding_service
from app.api.router import api_router
from app.marketplace.exceptions import MarketplaceError
from app.realtime_voice import safety as realtime_safety
from app.realtime_voice.exceptions import RealtimeVoiceError
from app.api.v1 import developer_openapi
from app.avatar.base import AvatarError
from app.avatar.jobs import recover_interrupted as recover_avatar_jobs
from app.avatar.jobs import set_event_loop as set_avatar_jobs_loop
from app.avatar.jobs import shutdown as avatar_jobs_shutdown
from app.avatar.storage import AvatarStorageError
from app.billing.exceptions import UsageLimitError
from app.core.api_cors import DeveloperApiCorsMiddleware
from app.core.config import APP_VERSION, get_settings
from app.core.logging_setup import configure_logging
from app.core.production import validate_production
from app.core.request_id import RequestIdMiddleware
from app.core.trusted_hosts import HostCheckMiddleware
from app.core.security_headers import SecurityHeadersMiddleware
from app.core.upload_limit import UploadSizeLimitMiddleware, too_large_message
from app.developer import webhooks
from app.developer.errors import ApiError, code_for, is_developer_api
from app.developer.usage import DeveloperApiUsageMiddleware
from app.schemas.health import RootResponse
from app.services import monitoring
from app.services.admin_bootstrap import promote_initial_admin
from app.services.auth_service import AccountLockedError
from app.services.errors import (
    AuthenticationError,
    ConflictError,
    ForbiddenError,
    InvalidInputError,
    MaintenanceError,
    NotFoundError,
)
from app.services.file_storage import FileTooLargeError
from app.services.ingestion_service import IngestionError
from app.services.qdrant_service import VectorStoreError
from app.services.rate_limit import RateLimitedError
from app.voice.base import VoiceError
from app.voice.cleanup import run_periodically as clean_voice_audio_periodically

settings = get_settings()
configure_logging(settings.log_level, settings.log_format)
logger = logging.getLogger(__name__)
realtime_safety.install_log_redaction()  # no WebSocket tickets in uvicorn's request logs
# ENVIRONMENT=production: refuse to start with development or unsafe settings.
validate_production(settings)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # Schema changes are applied by `python -m app.db.migrate` before the API starts.
    # Load (and on first run, download) the embedding model without blocking startup.
    threading.Thread(target=get_embedding_service().warm_up, daemon=True).start()
    # INITIAL_ADMIN_EMAIL: make that existing account an administrator while none exists.
    await run_in_threadpool(promote_initial_admin)
    # Video jobs cut off by a restart are marked failed so clients stop waiting.
    await run_in_threadpool(recover_avatar_jobs)
    # Video workers run async provider calls (TTS) on this loop, where the shared clients live.
    set_avatar_jobs_loop(asyncio.get_running_loop())
    # Agent runs (Phase 16) also call async providers from worker threads on this loop;
    # runs cut off by a restart are marked failed (waiting confirmations stay waiting).
    agent_runner.set_event_loop(asyncio.get_running_loop())
    await run_in_threadpool(agent_runner.recover_interrupted)
    # Delete generated speech and videos past their retention time, hourly.
    cleanup = asyncio.create_task(clean_voice_audio_periodically())
    # Webhook deliveries are sent (and retried) by a background thread, never in requests.
    webhooks.start_worker()
    yield
    # Shutdown (SIGTERM): stop taking work, with bounded waits. Runs and videos cut off
    # here are marked failed by recover_interrupted on the next start.
    logger.info("Shutting down: stopping background workers")
    webhooks.stop_worker()
    agent_runner.shutdown()
    avatar_jobs_shutdown()
    cleanup.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await cleanup
    await run_in_threadpool(monitoring.flush, 3.0)


app = FastAPI(
    title=settings.app_name,
    version=APP_VERSION,
    lifespan=lifespan,
    # API_DOCS_ENABLED (default: on in development, off in production).
    docs_url="/docs" if settings.docs_enabled else None,
    redoc_url="/redoc" if settings.docs_enabled else None,
    openapi_url="/openapi.json" if settings.docs_enabled else None,
)

# Added before CORS so CORS stays outermost and 413 responses still carry CORS headers.
app.add_middleware(DeveloperApiUsageMiddleware)
app.add_middleware(UploadSizeLimitMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Added after (so outside) the frontend CORS: /api/v1 has its own, credential-free CORS.
app.add_middleware(DeveloperApiCorsMiddleware)
if settings.allowed_hosts:
    # ALLOWED_HOSTS: reject other Host headers; health probes are exempt (app/core/trusted_hosts.py).
    app.add_middleware(HostCheckMiddleware, allowed_hosts=settings.allowed_hosts)
app.add_middleware(RequestIdMiddleware)


def _respond(
    request: Request,
    status_code: int,
    detail: object,
    *,
    code: str | None = None,
    extra: dict | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """The app's error response. The internal API keeps {"detail": ...}; the developer
    API (/api/v1) uses {"error", "message", "request_id"} (stack traces never leak)."""
    request_id = getattr(request.state, "request_id", None)
    if request_id:  # also on responses produced outside the request-id middleware (500s)
        headers = {**(headers or {}), "X-Request-ID": request_id}
    if is_developer_api(request.url.path):
        message = detail if isinstance(detail, str) else "The request is invalid."
        body: dict = {
            "error": code if code and code != "maintenance" else code_for(status_code),
            "message": message,
            "request_id": request_id,
        }
        if not isinstance(detail, str):
            body["details"] = detail
        if extra and "retry_after" in extra:
            body["retry_after"] = extra["retry_after"]
        return JSONResponse(status_code=status_code, content=body, headers=headers)
    return JSONResponse(status_code=status_code, content={"detail": detail, **(extra or {})}, headers=headers)


@app.exception_handler(ApiError)
async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    extra = {"retry_after": exc.retry_after} if exc.retry_after is not None else None
    return _respond(request, exc.status_code, exc.message, code=exc.code, extra=extra, headers=exc.headers)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Framework errors (unknown path, wrong method) in the same format as everything else."""
    detail = exc.detail if isinstance(exc.detail, str) else "Request failed."
    return _respond(request, exc.status_code, detail, headers=getattr(exc, "headers", None))


@app.exception_handler(RealtimeVoiceError)
async def realtime_voice_error_handler(request: Request, exc: RealtimeVoiceError) -> JSONResponse:
    """Phase 17: {"detail": safe message, "code": stable code} (docs/phase17/contract.md)."""
    return _respond(request, exc.status_code, exc.message, code=exc.code, extra={"code": exc.code})


@app.exception_handler(MarketplaceError)
async def marketplace_error_handler(request: Request, exc: MarketplaceError) -> JSONResponse:
    """Phase 18: {"detail": safe message, "code": stable code, ...} (docs/phase18/contract.md)."""
    return _respond(request, exc.status_code, exc.message, code=exc.code, extra={"code": exc.code, **exc.extra})


@app.exception_handler(UsageLimitError)
async def usage_limit_handler(request: Request, exc: UsageLimitError) -> JSONResponse:
    info = exc.args[0] if exc.args and isinstance(exc.args[0], dict) else {}
    return _respond(request, 429, str(info.get("message") or "Usage limit reached."), code="usage_limit_reached")



# Error events (admin area) store the safe user-facing message, the masked endpoint
# and the code location; never request bodies, prompts, keys or tokens.


@app.exception_handler(LLMError)
async def llm_error_handler(request: Request, exc: LLMError) -> JSONResponse:
    # Technical detail (provider status codes, messages) stays in the logs.
    logger.warning("LLM error %s: %s", type(exc).__name__, exc)
    monitoring.error(exc, request=request, status_code=exc.status_code, category="llm", message=exc.user_message)
    return _respond(request, exc.status_code, exc.user_message)


@app.exception_handler(VoiceError)
async def voice_error_handler(request: Request, exc: VoiceError) -> JSONResponse:
    # Provider details stay in the logs; audio and transcripts are never logged.
    logger.warning("Voice error %s: %s", type(exc).__name__, exc)
    if exc.status_code >= 500:  # a bad upload or silence isn't a system error
        monitoring.error(exc, request=request, status_code=exc.status_code, category="voice", message=exc.user_message)
    return _respond(request, exc.status_code, exc.user_message)


@app.exception_handler(AvatarError)
async def avatar_error_handler(request: Request, exc: AvatarError) -> JSONResponse:
    logger.warning("Avatar error %s: %s", type(exc).__name__, exc)
    if exc.status_code >= 500:
        monitoring.error(exc, request=request, status_code=exc.status_code, category="avatar", message=exc.user_message)
    return _respond(request, exc.status_code, exc.user_message)


@app.exception_handler(AvatarStorageError)
async def avatar_storage_error_handler(request: Request, exc: AvatarStorageError) -> JSONResponse:
    logger.error("Avatar storage error: %s", exc)
    monitoring.error(exc, request=request, status_code=503, category="storage", message="Avatar storage failed")
    return _respond(request, 503, "Avatar files can't be stored right now.")


@app.exception_handler(RateLimitedError)
async def rate_limited_handler(request: Request, exc: RateLimitedError) -> JSONResponse:
    public = request.url.path.startswith("/api/public/")
    monitoring.security(
        "PUBLIC_ABUSE_DETECTED" if public else "RATE_LIMIT_EXCEEDED",
        "medium" if public else "low",
        request=request,
        dedupe=True,
    )
    return _respond(request, 429, str(exc))


@app.exception_handler(AccountLockedError)
async def account_locked_handler(request: Request, exc: AccountLockedError) -> JSONResponse:
    return _respond(request, 429, str(exc))


@app.exception_handler(MaintenanceError)
async def maintenance_handler(request: Request, exc: MaintenanceError) -> JSONResponse:
    return _respond(request, 503, str(exc), extra={"maintenance": True}, code="maintenance")


@app.exception_handler(NotFoundError)
async def not_found_handler(request: Request, exc: NotFoundError) -> JSONResponse:
    return _respond(request, 404, str(exc))


@app.exception_handler(InvalidInputError)
async def invalid_input_handler(request: Request, exc: InvalidInputError) -> JSONResponse:
    return _respond(request, 400, str(exc))


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    # 400 with the field-level details; the submitted values are left out so
    # passwords are never echoed back.
    errors = [{"loc": err.get("loc"), "msg": err.get("msg"), "type": err.get("type")} for err in exc.errors()]
    return _respond(request, 400, jsonable_encoder(errors), code="validation_error")


@app.exception_handler(AuthenticationError)
async def authentication_error_handler(request: Request, exc: AuthenticationError) -> JSONResponse:
    return _respond(request, 401, str(exc))


@app.exception_handler(ForbiddenError)
async def forbidden_handler(request: Request, exc: ForbiddenError) -> JSONResponse:
    return _respond(request, 403, str(exc))


@app.exception_handler(ConflictError)
async def conflict_handler(request: Request, exc: ConflictError) -> JSONResponse:
    return _respond(request, 409, str(exc))


@app.exception_handler(FileTooLargeError)
async def file_too_large_handler(request: Request, __: FileTooLargeError) -> JSONResponse:
    return _respond(request, 413, too_large_message())


@app.exception_handler(VectorStoreError)
@app.exception_handler(EmbeddingError)
async def memory_unavailable_handler(request: Request, exc: Exception) -> JSONResponse:
    # Safe, generic messages only: no hosts, credentials or internals.
    category = "vector_store" if isinstance(exc, VectorStoreError) else "embedding"
    monitoring.error(exc, request=request, status_code=503, category=category, message=str(exc))
    return _respond(request, 503, str(exc))


@app.exception_handler(IngestionError)
async def ingestion_error_handler(request: Request, exc: IngestionError) -> JSONResponse:
    monitoring.error(exc, request=request, status_code=502, category="ingestion", message=str(exc))
    return _respond(request, 502, str(exc))


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error: %s", exc)
    # Only the exception type and location: its message could contain data.
    monitoring.error(exc, request=request, status_code=500, category="internal")
    return _respond(request, 500, "Internal server error")


@app.get("/", response_model=RootResponse, tags=["root"])
async def root() -> RootResponse:
    return RootResponse(message="Clone Me API", status="running")


app.include_router(api_router)


@app.get("/api/v1/openapi.json", include_in_schema=False)
async def developer_openapi_json() -> JSONResponse:
    """OpenAPI for the developer API only (/api/v1)."""
    return JSONResponse(developer_openapi(app))


@app.get("/api/v1/docs", include_in_schema=False)
async def developer_api_docs():
    from fastapi.openapi.docs import get_swagger_ui_html

    return get_swagger_ui_html(openapi_url="/api/v1/openapi.json", title="Clone Me Developer API")
