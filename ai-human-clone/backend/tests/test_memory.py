"""Phase 4: chunking, embeddings, Qdrant indexing and semantic search.

Qdrant is the real engine in in-memory mode (tests/conftest.py); embeddings are
a bag-of-words fake, so texts that share words are similar.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from qdrant_client.models import Distance
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Document
from app.services import indexing_service, retrieval_service
from app.services.qdrant_service import QdrantService, VectorStoreError, point_id
from app.services.text_chunker import ChunkingConfig, chunk_text
from tests.conftest import USER

CLONE = {"name": "Ayaan AI", "bio": "Developer", "owner_consent": True}
SKILLS = "Ayaan knows Python, Django, FastAPI and Docker. He builds AI programming tools."
HOBBIES = "On weekends Ayaan plays cricket and drinks chai with friends in Karachi."


@pytest.fixture
def owner(client: TestClient, registered: dict) -> TestClient:
    return client


@pytest.fixture
def other(make_client) -> TestClient:
    browser = make_client()
    assert browser.post(
        "/api/auth/register", json={**USER, "email": "sara@example.com", "username": "sara"}
    ).status_code == 201
    return browser


def new_clone(client: TestClient, name: str = "Ayaan AI") -> str:
    response = client.post("/api/clones", json={**CLONE, "name": name})
    assert response.status_code == 201
    return response.json()["id"]


def add_manual(client: TestClient, clone_id: str, title: str, content: str) -> dict:
    response = client.post(f"/api/clones/{clone_id}/knowledge", json={"title": title, "content": content})
    assert response.status_code == 201, response.text
    return response.json()


def search(client: TestClient, clone_id: str, query: str, **body):
    return client.post(f"/api/clones/{clone_id}/knowledge/search", json={"query": query, **body})


# --- Chunking ------------------------------------------------------------------


def test_chunks_respect_size_words_and_paragraphs():
    text = "\n\n".join(
        f"Paragraph {p} begins. " + " ".join(f"Sentence {s} of paragraph {p}." for s in range(10)) for p in range(6)
    )
    chunks = chunk_text(text, ChunkingConfig(chunk_size=300, overlap=60))
    words = text.split()
    assert len(chunks) > 1
    assert all(len(c) <= 300 for c in chunks)
    assert all(word in words for c in chunks for word in c.split())  # no word cut in half
    assert set(words) <= set(" ".join(chunks).split())  # nothing lost
    assert any("\n\n" in c for c in chunks)  # paragraph boundaries kept


def test_chunks_overlap_with_previous_chunk():
    text = " ".join(f"Fact number {i} is here." for i in range(80))
    chunks = chunk_text(text, ChunkingConfig(chunk_size=200, overlap=50))
    for previous, current in zip(chunks, chunks[1:]):
        first_words = " ".join(current.split()[:3])
        assert first_words in previous  # starts with the end of the previous chunk


def test_chunking_edge_cases():
    config = ChunkingConfig(chunk_size=100, overlap=20)
    assert chunk_text("", config) == []
    assert chunk_text("   \n\n  ", config) == []
    assert chunk_text("Short text.", config) == ["Short text."]
    assert [len(c) for c in chunk_text("x" * 250, config)] == [100, 100, 50]  # one giant "word"
    urdu = chunk_text("یہ پہلا جملہ ہے۔ یہ دوسرا جملہ ہے۔ " * 20, config)
    assert len(urdu) > 1 and all(len(c) <= 100 for c in urdu)


@pytest.mark.parametrize(("size", "overlap"), [(10, 0), (100, 60), (100, -1)])
def test_invalid_chunking_config_rejected(size, overlap):
    with pytest.raises(ValueError):
        ChunkingConfig(chunk_size=size, overlap=overlap)


# --- Embeddings and collection ---------------------------------------------


def test_embedding_generation(embeddings):
    vectors = embeddings.embed_documents(["python fastapi", "cricket chai"])
    assert len(vectors) == 2 and all(len(v) == embeddings.dimension for v in vectors)
    assert embeddings.embed_text("python") != embeddings.embed_text("cricket")


def test_create_collection_with_model_dimension_and_indexes(monkeypatch):
    store = QdrantService(url=":memory:", collection_name="test_memories")
    # In-memory Qdrant doesn't keep payload indexes, so record the requests instead.
    requested: list[str] = []
    monkeypatch.setattr(store.client, "create_payload_index", lambda **kw: requested.append(kw["field_name"]))
    store.ensure_collection(384)
    info = store.client.get_collection("test_memories")
    assert info.config.params.vectors.size == 384
    assert info.config.params.vectors.distance == Distance.COSINE
    assert sorted(requested) == ["clone_id", "document_id", "user_id"]
    store.ensure_collection(384)  # idempotent: same collection, no error
    with pytest.raises(VectorStoreError, match="384-dimensional"):
        store.ensure_collection(768)  # model changed without recreating the collection


def test_qdrant_health(client: TestClient, qdrant, monkeypatch):
    body = client.get("/api/health/qdrant").json()
    assert body["status"] == "healthy" and body["collection"] == "clone_memories"
    assert "url" not in body and "api_key" not in body

    monkeypatch.setattr(qdrant, "health_check", lambda: False)
    assert client.get("/api/health/qdrant").json()["status"] == "unavailable"


# --- Indexing --------------------------------------------------------------------


def test_upload_is_indexed_with_full_metadata(owner: TestClient, qdrant, registered: dict):
    clone_id = new_clone(owner)
    doc = owner.post(
        f"/api/clones/{clone_id}/documents", files={"file": ("cv.txt", SKILLS.encode(), "text/plain")}, data={"title": "My CV"}
    ).json()
    assert (doc["status"], doc["indexing_status"], doc["chunk_count"]) == ("ready", "indexed", 1)
    assert doc["indexed_at"] is not None

    points, _ = qdrant.client.scroll("clone_memories", with_payload=True)
    assert len(points) == 1
    assert points[0].id == point_id(uuid.UUID(doc["id"]), 0)  # stable UUID, not an integer
    assert points[0].payload == {
        "user_id": registered["id"],
        "clone_id": clone_id,
        "document_id": doc["id"],
        "chunk_index": 0,
        "source_type": "file",
        "title": "My CV",
        "text": SKILLS,
    }


def test_manual_knowledge_is_indexed(owner: TestClient, qdrant):
    clone_id = new_clone(owner)
    doc = add_manual(owner, clone_id, "Hobbies", HOBBIES)
    assert doc["indexing_status"] == "indexed" and doc["chunk_count"] == 1
    points, _ = qdrant.client.scroll("clone_memories", with_payload=True)
    assert points[0].payload["source_type"] == "manual_text"


def test_long_document_produces_many_unique_chunks(owner: TestClient, qdrant, monkeypatch):
    monkeypatch.setattr(get_settings(), "chunk_size", 200)
    monkeypatch.setattr(get_settings(), "chunk_overlap", 40)
    clone_id = new_clone(owner)
    text = " ".join(f"Project {i} used Python and FastAPI for client work." for i in range(40))
    doc = add_manual(owner, clone_id, "Projects", text)
    assert doc["chunk_count"] > 5
    points, _ = qdrant.client.scroll("clone_memories", limit=100)
    assert len({p.id for p in points}) == doc["chunk_count"]


def test_index_endpoint_and_idempotence(owner: TestClient, qdrant, db_session: Session):
    clone_id = new_clone(owner)
    doc = add_manual(owner, clone_id, "Skills", SKILLS)
    # Simulate a document that was stored but never indexed.
    stored = db_session.get(Document, uuid.UUID(doc["id"]))
    stored.indexing_status = "not_indexed"
    db_session.commit()
    qdrant.delete_document_chunks(stored.id)

    result = owner.post(f"/api/clones/{clone_id}/documents/{doc['id']}/index")
    assert result.status_code == 200
    assert result.json() == {"document_id": doc["id"], "status": "indexed", "chunk_count": 1, "error": None}
    # Calling again doesn't duplicate anything.
    owner.post(f"/api/clones/{clone_id}/documents/{doc['id']}/index")
    assert qdrant.count_chunks(clone_id=uuid.UUID(clone_id)) == 1


def test_index_requires_ready_text(owner: TestClient):
    clone_id = new_clone(owner)
    from tests.test_documents import make_pdf

    failed = owner.post(
        f"/api/clones/{clone_id}/documents", files={"file": ("scan.pdf", make_pdf(None), "application/pdf")}
    ).json()
    assert failed["status"] == "failed" and failed["indexing_status"] == "not_indexed"
    assert owner.post(f"/api/clones/{clone_id}/documents/{failed['id']}/index").status_code == 400


def test_reindex_replaces_vectors(owner: TestClient, qdrant, monkeypatch):
    clone_id = new_clone(owner)
    text = " ".join(f"Skill {i} is Python programming." for i in range(30))
    doc = add_manual(owner, clone_id, "Skills", text)
    first_count = doc["chunk_count"]

    monkeypatch.setattr(get_settings(), "chunk_size", 150)  # e.g. chunk settings changed
    monkeypatch.setattr(get_settings(), "chunk_overlap", 30)
    result = owner.post(f"/api/clones/{clone_id}/documents/{doc['id']}/reindex").json()
    assert result["status"] == "indexed" and result["chunk_count"] > first_count
    # Exactly the new chunks exist: old ones were deleted, nothing appended twice.
    assert qdrant.count_chunks(clone_id=uuid.UUID(clone_id)) == result["chunk_count"]


def test_changed_text_leaves_no_old_vectors(owner: TestClient, qdrant, db_session: Session):
    clone_id = new_clone(owner)
    doc = add_manual(owner, clone_id, "Notes", SKILLS + " " + HOBBIES)
    stored = db_session.get(Document, uuid.UUID(doc["id"]))
    stored.extracted_text = "Ayaan now works mostly with Rust and embedded systems."
    db_session.commit()
    indexing_service.index_document(db_session, stored)

    clone = stored.clone
    hits = retrieval_service.search_knowledge(clone, "cricket chai Karachi", 5, min_score=0.0)
    assert all("cricket" not in hit.text for hit in hits)
    assert qdrant.count_chunks(clone_id=clone.id) == 1


def test_embedding_failure_marks_indexing_failed(owner: TestClient, embeddings, qdrant):
    clone_id = new_clone(owner)
    embeddings.fail = True
    doc = add_manual(owner, clone_id, "Skills", SKILLS)
    assert doc["status"] == "ready"  # the text is still saved
    assert doc["indexing_status"] == "indexing_failed"
    assert doc["indexing_error"] and "Traceback" not in doc["indexing_error"]
    assert qdrant.count_chunks(clone_id=uuid.UUID(clone_id)) == 0

    embeddings.fail = False  # recovered: retry indexing
    result = owner.post(f"/api/clones/{clone_id}/documents/{doc['id']}/index").json()
    assert result["status"] == "indexed"


def test_qdrant_failure_never_reports_indexed(owner: TestClient, qdrant, monkeypatch):
    clone_id = new_clone(owner)

    def broken_upsert(chunks, vectors):
        raise VectorStoreError("Could not store vectors in the memory store")

    monkeypatch.setattr(qdrant, "upsert_chunks", broken_upsert)
    doc = add_manual(owner, clone_id, "Skills", SKILLS)
    assert doc["indexing_status"] == "indexing_failed"
    assert doc["chunk_count"] == 0 and doc["indexed_at"] is None
    assert qdrant.count_chunks(clone_id=uuid.UUID(clone_id)) == 0
    detail = owner.get(f"/api/clones/{clone_id}/documents/{doc['id']}").json()
    assert detail["indexing_status"] == "indexing_failed"


# --- Deleting vectors ------------------------------------------------------------


def test_delete_document_removes_only_its_vectors(owner: TestClient, qdrant):
    clone_id = new_clone(owner)
    skills = add_manual(owner, clone_id, "Skills", SKILLS)
    hobbies = add_manual(owner, clone_id, "Hobbies", HOBBIES)
    assert owner.delete(f"/api/clones/{clone_id}/documents/{skills['id']}").status_code == 204
    assert qdrant.count_chunks(clone_id=uuid.UUID(clone_id), document_id=uuid.UUID(skills["id"])) == 0
    assert qdrant.count_chunks(clone_id=uuid.UUID(clone_id), document_id=uuid.UUID(hobbies["id"])) == 1


def test_delete_is_refused_while_qdrant_is_down(owner: TestClient, qdrant, monkeypatch):
    clone_id = new_clone(owner)
    doc = add_manual(owner, clone_id, "Skills", SKILLS)

    def down(document_id):
        raise VectorStoreError("Could not remove vectors from the memory store")

    monkeypatch.setattr(qdrant, "delete_document_chunks", down)
    response = owner.delete(f"/api/clones/{clone_id}/documents/{doc['id']}")
    assert response.status_code == 503
    assert "memory store" in response.json()["detail"]
    # Nothing was deleted, so no vectors are orphaned; the user can retry later.
    assert owner.get(f"/api/clones/{clone_id}/documents/{doc['id']}").status_code == 200


# --- Semantic search -------------------------------------------------------------


def test_semantic_search_returns_relevant_chunks(owner: TestClient):
    clone_id = new_clone(owner)
    add_manual(owner, clone_id, "Skills", SKILLS)
    add_manual(owner, clone_id, "Hobbies", HOBBIES)

    body = search(owner, clone_id, "What programming skills like Python does Ayaan have?").json()
    assert body["query"] == "What programming skills like Python does Ayaan have?"
    assert body["results"][0]["title"] == "Skills"
    first = body["results"][0]
    assert set(first) == {"score", "document_id", "title", "source_type", "chunk_index", "text"}
    assert first["text"] == SKILLS and 0 < first["score"] <= 1
    scores = [r["score"] for r in body["results"]]
    assert scores == sorted(scores, reverse=True)


def test_search_top_k_limits_results(owner: TestClient):
    clone_id = new_clone(owner)
    for i in range(6):
        add_manual(owner, clone_id, f"Note {i}", f"Ayaan note {i} about Python and FastAPI projects.")
    assert len(search(owner, clone_id, "Python FastAPI projects", top_k=3).json()["results"]) == 3


@pytest.mark.parametrize("top_k", [0, -1, 21, 1000, "five"])
def test_invalid_top_k_rejected(owner: TestClient, top_k):
    clone_id = new_clone(owner)
    assert search(owner, clone_id, "python", top_k=top_k).status_code == 400


@pytest.mark.parametrize("query", ["", "   ", "x" * 1001])
def test_invalid_query_rejected(owner: TestClient, query):
    clone_id = new_clone(owner)
    assert search(owner, clone_id, query).status_code == 400


def test_empty_knowledge_is_handled(owner: TestClient):
    clone_id = new_clone(owner)
    response = search(owner, clone_id, "anything")
    assert response.status_code == 200
    assert response.json() == {
        "query": "anything",
        "results": [],
        "message": "No indexed knowledge is available for this clone.",
    }


def test_similarity_threshold_drops_unrelated_results(owner: TestClient, monkeypatch):
    clone_id = new_clone(owner)
    add_manual(owner, clone_id, "Skills", SKILLS)

    unrelated = search(owner, clone_id, "weather forecast tomorrow morning").json()
    assert unrelated["results"] == []
    assert unrelated["message"] == "No sufficiently relevant knowledge was found for this question."

    assert search(owner, clone_id, "Python Django FastAPI").json()["results"]  # related: found
    monkeypatch.setattr(get_settings(), "min_similarity_score", 0.99)  # stricter threshold
    assert search(owner, clone_id, "Python Django FastAPI").json()["results"] == []


def test_search_is_filtered_by_clone(owner: TestClient):
    first = new_clone(owner, "First")
    second = new_clone(owner, "Second")
    add_manual(owner, first, "First skills", SKILLS)
    add_manual(owner, second, "Second skills", SKILLS.replace("Ayaan", "Bilal"))
    results = search(owner, first, "Python FastAPI Docker").json()["results"]
    assert results and {r["title"] for r in results} == {"First skills"}


def test_search_can_filter_by_document(owner: TestClient, db_session: Session):
    clone_id = new_clone(owner)
    skills = add_manual(owner, clone_id, "Skills", SKILLS)
    add_manual(owner, clone_id, "More skills", "Ayaan also knows Python testing with pytest.")
    clone = db_session.get(Document, uuid.UUID(skills["id"])).clone
    hits = retrieval_service.search_knowledge(clone, "Python", 5, document_id=uuid.UUID(skills["id"]))
    assert hits and {h.document_id for h in hits} == {skills["id"]}


def test_unauthenticated_search_rejected(make_client, owner: TestClient):
    clone_id = new_clone(owner)
    assert search(make_client(), clone_id, "python").status_code == 401


def test_memory_is_isolated_between_users(owner: TestClient, other: TestClient):
    clone_a = new_clone(owner, "Clone A")
    add_manual(owner, clone_a, "Knowledge A", "User A secret: Ayaan builds Python and FastAPI systems.")
    clone_b = new_clone(other, "Clone B")
    add_manual(other, clone_b, "Knowledge B", "User B secret: Sara builds Python and Django systems.")

    # B searching A's clone fails; A searching B's clone fails.
    assert search(other, clone_a, "Python systems").status_code == 404
    assert search(owner, clone_b, "Python systems").status_code == 404
    # Even when public, only the owner may search its memory.
    owner.patch(f"/api/clones/{clone_a}", json={"visibility": "public"})
    assert search(other, clone_a, "Python systems").status_code == 403

    # Each owner succeeds on their own clone and only ever sees their own knowledge.
    a_results = search(owner, clone_a, "Python systems").json()["results"]
    b_results = search(other, clone_b, "Python systems").json()["results"]
    assert a_results and all("User A" in r["text"] for r in a_results)
    assert b_results and all("User B" in r["text"] for r in b_results)
    # Indexing/reindexing someone else's document is refused too.
    b_doc = other.get(f"/api/clones/{clone_b}/documents").json()[0]["id"]
    assert owner.post(f"/api/clones/{clone_b}/documents/{b_doc}/reindex").status_code == 404
    assert owner.post(f"/api/clones/{clone_a}/documents/{b_doc}/index").status_code == 404


def test_clone_memory_stats(owner: TestClient, embeddings):
    clone_id = new_clone(owner)
    add_manual(owner, clone_id, "Skills", SKILLS)
    add_manual(owner, clone_id, "Hobbies", HOBBIES)
    embeddings.fail = True
    add_manual(owner, clone_id, "Broken", "This one fails to index because embeddings are down.")
    clone = owner.get(f"/api/clones/{clone_id}").json()
    assert (clone["knowledge_count"], clone["indexed_count"], clone["chunk_count"]) == (3, 2, 2)
