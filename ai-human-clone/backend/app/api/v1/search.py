"""POST /api/v1/clones/{clone_id}/search: semantic search in a clone's knowledge.

Scope rules:
- `clone:search`: all of the clone's knowledge, private documents included.
- `clone:knowledge:read` (without clone:search): only documents marked public; the
  search is restricted to an allowlist of those document ids.
- neither: 403 permission_denied.

Results carry the document title, source type, score and a trimmed snippet (at most
SNIPPET_CHARS characters), never file names, paths or whole documents. The search
reuses retrieval_service.search_knowledge (no second RAG implementation).
"""

import time
import uuid

from fastapi import APIRouter, Request
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from app.api.deps import DbSession
from app.developer import access, feature_limits
from app.developer.auth import ApiAuth
from app.developer.errors import ApiError
from app.models import Document
from app.schemas.api_v1 import SNIPPET_CHARS, ApiSearchRequest, ApiSearchResponse, ApiSearchResult
from app.services import ingestion_service, retrieval_service

router = APIRouter(tags=["Knowledge"])


def _snippet(text: str) -> str:
    text = " ".join((text or "").split())
    if len(text) <= SNIPPET_CHARS:
        return text
    return text[: SNIPPET_CHARS - 1].rstrip() + "…"


@router.post("/clones/{clone_id}/search", response_model=ApiSearchResponse, summary="Search a clone's knowledge")
async def search(
    clone_id: uuid.UUID, data: ApiSearchRequest, request: Request, principal: ApiAuth, db: DbSession
) -> ApiSearchResponse:
    """Find the passages of the clone's knowledge most relevant to `query` (not an answer).

    Scope: `clone:search` (all knowledge) or `clone:knowledge:read` (public documents only).
    """
    if principal.has("clone:search"):
        scope = "all"
    elif principal.has("clone:knowledge:read"):
        scope = "public"
    else:
        raise ApiError(403, "permission_denied", "This API key is missing the scope: clone:search or clone:knowledge:read.")
    clone = access.get_clone(db, principal, clone_id)
    feature_limits.mark_clone(request, clone)

    stats = ingestion_service.knowledge_stats(db, [clone.id]).get(clone.id, {})
    if not stats.get("indexed_count"):
        return ApiSearchResponse(query=data.query, scope=scope, results=[])

    document_ids = None
    if scope == "public":
        document_ids = list(
            db.scalars(select(Document.id).where(Document.clone_id == clone.id, Document.visibility == "public"))
        )
        if not document_ids:
            return ApiSearchResponse(query=data.query, scope=scope, results=[])

    started = time.monotonic()
    hits = await run_in_threadpool(
        retrieval_service.search_knowledge, clone, data.query, data.top_k, document_ids=document_ids
    )
    feature_limits.record(
        "API_SEARCH", principal, request, clone,
        duration_ms=int((time.monotonic() - started) * 1000), output_units=len(hits),
    )
    return ApiSearchResponse(
        query=data.query,
        scope=scope,
        results=[
            ApiSearchResult(title=hit.title, source_type=hit.source_type, score=round(hit.score, 4), snippet=_snippet(hit.text))
            for hit in hits
        ],
    )
