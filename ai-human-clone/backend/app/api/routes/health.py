import time

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.ai import get_llm_provider
from app.api.deps import CurrentUser
from app.ai.embedding_service import EmbeddingError, get_embedding_service
from app.db.session import check_database
from app.schemas.health import HealthResponse, LLMStatus, QdrantHealthResponse, ServicesHealthResponse
from app.services.qdrant_service import get_qdrant_service

router = APIRouter(prefix="/health", tags=["health"])


@router.get("", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Liveness probe: the API process is up."""
    return HealthResponse(status="healthy")


@router.get("/live")
async def live() -> dict[str, str]:
    """Liveness for orchestrators: the process answers. Checks nothing else, so a database
    outage never gets healthy containers restarted."""
    return {"status": "alive"}


@router.get("/ready")
async def ready() -> JSONResponse:
    """Readiness: PostgreSQL and Qdrant answer. 503 until both do. Only booleans: no hosts,
    versions or settings."""
    database_ok = await run_in_threadpool(check_database)
    qdrant_ok = await run_in_threadpool(get_qdrant_service().health_check)
    checks = {"database": database_ok, "qdrant": qdrant_ok}
    if database_ok and qdrant_ok:
        return JSONResponse({"status": "ready", "checks": checks})
    return JSONResponse({"status": "not_ready", "checks": checks}, status_code=503)


@router.get("/services", response_model=ServicesHealthResponse)
async def services_health() -> ServicesHealthResponse:
    """Readiness check for PostgreSQL, Qdrant and the local embedding model."""
    qdrant = get_qdrant_service()
    database_ok = await run_in_threadpool(check_database)
    qdrant_ok = await run_in_threadpool(qdrant.is_available)
    collection_exists = qdrant_ok and await run_in_threadpool(qdrant.collection_exists)

    return ServicesHealthResponse(
        status="healthy" if database_ok and qdrant_ok else "degraded",
        database=database_ok,
        qdrant=qdrant_ok,
        qdrant_collection=qdrant.collection_name,
        qdrant_collection_exists=collection_exists,
        embedding_model_ready=get_embedding_service().is_ready,
    )


@router.get("/qdrant", response_model=QdrantHealthResponse)
async def qdrant_health() -> QdrantHealthResponse:
    """Whether the vector store is reachable, and whether its collection matches the embedding model."""
    qdrant = get_qdrant_service()
    healthy = await run_in_threadpool(qdrant.health_check)
    size = await run_in_threadpool(qdrant.vector_size) if healthy else None
    return QdrantHealthResponse(
        status="healthy" if healthy else "unavailable",
        collection=qdrant.collection_name,
        collection_exists=size is not None,
        vector_size=size,
        embedding_dimension=await run_in_threadpool(_embedding_dimension),
    )


def _embedding_dimension() -> int | None:
    try:
        return get_embedding_service().dimension
    except EmbeddingError:
        return None


LLM_CHECK_CACHE_SECONDS = 60.0
_llm_check: tuple[float, dict] | None = None


def reset_llm_check_cache() -> None:
    global _llm_check
    _llm_check = None


@router.get("/llm", response_model=LLMStatus)
async def llm_health(_: CurrentUser) -> LLMStatus:
    """Checks the LLM API key and model without generating tokens.

    Logged-in users only, and cached for a minute: each check calls the provider's API,
    so an open endpoint would let anyone spend the platform's request quota and would
    tell strangers which provider/model is configured and whether its key works."""
    global _llm_check
    now = time.monotonic()
    if _llm_check is None or now - _llm_check[0] > LLM_CHECK_CACHE_SECONDS:
        _llm_check = (now, await get_llm_provider().check_connection())
    return LLMStatus.model_validate(_llm_check[1])
