"""Knowledge sources of a clone. Every route is owner-only: the clone is loaded
through get_managed_clone (404 for other users' private clones, 403 otherwise),
and documents are then looked up only within that clone."""

import uuid

from fastapi import APIRouter, File, Form, UploadFile, status

from app.api.deps import CurrentUser, DbSession
from app.schemas.document import (
    DocumentDetailResponse,
    DocumentListItem,
    DocumentResponse,
    IndexResult,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
    KnowledgeSearchResult,
    ManualKnowledgeCreate,
)
from app.services import clone_service, indexing_service, ingestion_service, retrieval_service

router = APIRouter(prefix="/clones/{clone_id}", tags=["knowledge"])


@router.post("/documents", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
def upload_document(
    clone_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    file: UploadFile = File(...),
    title: str | None = Form(default=None, max_length=255),
) -> DocumentResponse:
    """Upload a PDF, DOCX or TXT file. Text is extracted right away; check `status`
    (`ready` or `failed` with `error_message`)."""
    clone = clone_service.get_managed_clone(db, clone_id, user)
    document = ingestion_service.upload_file(
        db,
        clone,
        source=file.file,
        filename=file.filename,
        content_type=file.content_type,
        title=title,
    )
    return DocumentResponse.model_validate(document)


@router.post("/knowledge", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
def add_manual_knowledge(
    clone_id: uuid.UUID, data: ManualKnowledgeCreate, user: CurrentUser, db: DbSession
) -> DocumentResponse:
    clone = clone_service.get_managed_clone(db, clone_id, user)
    return DocumentResponse.model_validate(ingestion_service.add_manual_knowledge(db, clone, data))


@router.get("/documents", response_model=list[DocumentListItem])
def list_documents(clone_id: uuid.UUID, user: CurrentUser, db: DbSession) -> list[DocumentListItem]:
    clone = clone_service.get_managed_clone(db, clone_id, user)
    return [DocumentListItem.model_validate(d) for d in ingestion_service.list_documents(db, clone)]


@router.get("/documents/{document_id}", response_model=DocumentDetailResponse)
def get_document(
    clone_id: uuid.UUID, document_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> DocumentDetailResponse:
    clone = clone_service.get_managed_clone(db, clone_id, user)
    return DocumentDetailResponse.model_validate(ingestion_service.get_document(db, clone, document_id))


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(clone_id: uuid.UUID, document_id: uuid.UUID, user: CurrentUser, db: DbSession) -> None:
    clone = clone_service.get_managed_clone(db, clone_id, user)
    ingestion_service.delete_document(db, clone, document_id)


@router.post("/documents/{document_id}/retry", response_model=DocumentResponse)
def retry_document(
    clone_id: uuid.UUID, document_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> DocumentResponse:
    """Run text extraction again on the stored file of a failed document."""
    clone = clone_service.get_managed_clone(db, clone_id, user)
    return DocumentResponse.model_validate(ingestion_service.retry_document(db, clone, document_id))


# --- AI memory (vector index) ------------------------------------------------


def _index_result(document) -> IndexResult:
    return IndexResult(
        document_id=document.id,
        status=document.indexing_status,
        chunk_count=document.chunk_count,
        error=document.indexing_error,
    )


@router.post("/documents/{document_id}/index", response_model=IndexResult)
def index_document(clone_id: uuid.UUID, document_id: uuid.UUID, user: CurrentUser, db: DbSession) -> IndexResult:
    """Add a ready document to AI memory. Already indexed documents are left as they are
    (use /reindex to rebuild). On failure the result has status "indexing_failed" and `error`."""
    clone = clone_service.get_managed_clone(db, clone_id, user)
    document = ingestion_service.get_document(db, clone, document_id)
    if document.indexing_status != "indexed":
        document = indexing_service.index_document(db, document)
    return _index_result(document)


@router.post("/documents/{document_id}/reindex", response_model=IndexResult)
def reindex_document(clone_id: uuid.UUID, document_id: uuid.UUID, user: CurrentUser, db: DbSession) -> IndexResult:
    """Delete the document's vectors and rebuild them with the current chunking and embedding settings."""
    clone = clone_service.get_managed_clone(db, clone_id, user)
    document = ingestion_service.get_document(db, clone, document_id)
    return _index_result(indexing_service.index_document(db, document))


@router.post("/knowledge/search", response_model=KnowledgeSearchResponse)
def search_knowledge(
    clone_id: uuid.UUID, request: KnowledgeSearchRequest, user: CurrentUser, db: DbSession
) -> KnowledgeSearchResponse:
    """Semantic search in this clone's AI memory (owner only). Returns matching chunks, not an answer."""
    clone = clone_service.get_managed_clone(db, clone_id, user)
    stats = ingestion_service.knowledge_stats(db, [clone.id]).get(clone.id, {})
    if not stats.get("indexed_count"):
        return KnowledgeSearchResponse(
            query=request.query, results=[], message="No indexed knowledge is available for this clone."
        )

    hits = retrieval_service.search_knowledge(clone, request.query, request.top_k)
    return KnowledgeSearchResponse(
        query=request.query,
        results=[KnowledgeSearchResult(**hit.__dict__) for hit in hits],
        message=None if hits else "No sufficiently relevant knowledge was found for this question.",
    )
