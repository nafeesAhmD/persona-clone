from pydantic import BaseModel


class RootResponse(BaseModel):
    message: str
    status: str


class HealthResponse(BaseModel):
    status: str


class LLMStatus(BaseModel):
    provider: str
    configured: bool
    reachable: bool
    model: str
    error: str | None = None


class ServicesHealthResponse(BaseModel):
    status: str  # "healthy" when every dependency is up, otherwise "degraded"
    database: bool
    qdrant: bool
    qdrant_collection: str
    qdrant_collection_exists: bool
    embedding_model_ready: bool


class QdrantHealthResponse(BaseModel):
    status: str  # "healthy" | "unavailable"
    collection: str
    collection_exists: bool
    vector_size: int | None = None
    embedding_dimension: int | None = None
