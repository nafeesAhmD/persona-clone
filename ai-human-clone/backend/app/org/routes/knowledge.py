"""Organization knowledge management - allows editors to manage docs for org clones."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.clone_profile import CloneProfile
from app.org.authz.permissions import has_clone_role
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
from app.services import indexing_service, ingestion_service, retrieval_service

router = APIRouter(prefix="/organizations/{organization_id}/clones/{clone_id}", tags=["organizations-knowledge"])


def _check_clone_access(db, user_id: uuid.UUID, clone_id: uuid.UUID, roles: set[str]) -> CloneProfile:
    """Check if user has access to clone (owner or org member with role)."""
    clone = db.query(CloneProfile).filter(CloneProfile.id == clone_id).first()
    if not clone:
        raise HTTPException(status_code=404, detail="not_found")
    if clone.owner_id == user_id:
        return clone
    if clone.organization_id:
        ok, _ = has_clone_role(db, user_id, clone_id, roles)
        if ok:
            return clone
    raise HTTPException(status_code=403, detail="forbidden")


@router.post("/documents", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
def org_upload_document(
    organization_id: uuid.UUID,
    clone_id: uuid.UUID,
    file: UploadFile = File(...),
    title: str | None = Form(default=None, max_length=255),
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Upload a document to an organization clone (editor/owner)."""
    clone = _check_clone_access(db, current_user.id, clone_id, {"owner", "admin", "editor"})
    if clone.organization_id != organization_id:
        raise HTTPException(status_code=400, detail="clone_not_in_org")
    document = ingestion_service.upload_file(
        db, clone, source=file.file, filename=file.filename, content_type=file.content_type, title=title
    )
    return DocumentResponse.model_validate(document)


@router.post("/knowledge", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
def org_add_manual_knowledge(
    organization_id: uuid.UUID,
    clone_id: uuid.UUID,
    data: ManualKnowledgeCreate,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Add manual knowledge to an organization clone (editor/owner)."""
    clone = _check_clone_access(db, current_user.id, clone_id, {"owner", "admin", "editor"})
    if clone.organization_id != organization_id:
        raise HTTPException(status_code=400, detail="clone_not_in_org")
    return DocumentResponse.model_validate(ingestion_service.add_manual_knowledge(db, clone, data))


@router.get("/documents", response_model=list[DocumentListItem])
def org_list_documents(
    organization_id: uuid.UUID,
    clone_id: uuid.UUID,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    """List documents for an organization clone (editor/viewer/owner)."""
    clone = _check_clone_access(db, current_user.id, clone_id, {"owner", "admin", "editor", "viewer"})
    if clone.organization_id != organization_id:
        raise HTTPException(status_code=400, detail="clone_not_in_org")
    return [DocumentListItem.model_validate(d) for d in ingestion_service.list_documents(db, clone)]


@router.get("/documents/{document_id}", response_model=DocumentDetailResponse)
def org_get_document(
    organization_id: uuid.UUID,
    clone_id: uuid.UUID,
    document_id: uuid.UUID,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Get document details (editor/viewer/owner)."""
    clone = _check_clone_access(db, current_user.id, clone_id, {"owner", "admin", "editor", "viewer"})
    if clone.organization_id != organization_id:
        raise HTTPException(status_code=400, detail="clone_not_in_org")
    return DocumentDetailResponse.model_validate(ingestion_service.get_document(db, clone, document_id))


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def org_delete_document(
    organization_id: uuid.UUID,
    clone_id: uuid.UUID,
    document_id: uuid.UUID,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Delete a document (editor/owner)."""
    clone = _check_clone_access(db, current_user.id, clone_id, {"owner", "admin", "editor"})
    if clone.organization_id != organization_id:
        raise HTTPException(status_code=400, detail="clone_not_in_org")
    ingestion_service.delete_document(db, clone, document_id)


@router.post("/documents/{document_id}/retry", response_model=DocumentResponse)
def org_retry_document(
    organization_id: uuid.UUID,
    clone_id: uuid.UUID,
    document_id: uuid.UUID,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Retry text extraction on failed document (editor/owner)."""
    clone = _check_clone_access(db, current_user.id, clone_id, {"owner", "admin", "editor"})
    if clone.organization_id != organization_id:
        raise HTTPException(status_code=400, detail="clone_not_in_org")
    return DocumentResponse.model_validate(ingestion_service.retry_document(db, clone, document_id))


@router.post("/documents/{document_id}/index", response_model=IndexResult)
def org_index_document(
    organization_id: uuid.UUID,
    clone_id: uuid.UUID,
    document_id: uuid.UUID,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Index a document for AI memory (editor/owner)."""
    clone = _check_clone_access(db, current_user.id, clone_id, {"owner", "admin", "editor"})
    if clone.organization_id != organization_id:
        raise HTTPException(status_code=400, detail="clone_not_in_org")
    document = ingestion_service.get_document(db, clone, document_id)
    if document.indexing_status != "indexed":
        document = indexing_service.index_document(db, document)
    return IndexResult(
        document_id=document.id,
        status=document.indexing_status,
        chunk_count=document.chunk_count,
        error=document.indexing_error,
    )


@router.post("/documents/{document_id}/reindex", response_model=IndexResult)
def org_reindex_document(
    organization_id: uuid.UUID,
    clone_id: uuid.UUID,
    document_id: uuid.UUID,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Reindex a document (editor/owner)."""
    clone = _check_clone_access(db, current_user.id, clone_id, {"owner", "admin", "editor"})
    if clone.organization_id != organization_id:
        raise HTTPException(status_code=400, detail="clone_not_in_org")
    document = ingestion_service.get_document(db, clone, document_id)
    document = indexing_service.index_document(db, document)
    return IndexResult(
        document_id=document.id,
        status=document.indexing_status,
        chunk_count=document.chunk_count,
        error=document.indexing_error,
    )


@router.post("/knowledge/search", response_model=KnowledgeSearchResponse)
def org_search_knowledge(
    organization_id: uuid.UUID,
    clone_id: uuid.UUID,
    request: KnowledgeSearchRequest,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Semantic search in org clone's AI memory (viewer/editor/owner)."""
    clone = _check_clone_access(db, current_user.id, clone_id, {"owner", "admin", "editor", "viewer"})
    if clone.organization_id != organization_id:
        raise HTTPException(status_code=400, detail="clone_not_in_org")
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