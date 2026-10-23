"""Text embeddings: turning text into vectors for semantic search.

Embeddings are independent of the chat LLM (Claude/Gemini). The provider is
chosen by EMBEDDING_PROVIDER; to add one (e.g. a hosted embedding API),
implement EmbeddingService and register it in _PROVIDERS.
"""

import logging
import threading
from abc import ABC, abstractmethod
from functools import lru_cache

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)


class EmbeddingError(Exception):
    """The embedding model couldn't be loaded or failed to embed (mapped to HTTP 503)."""


class EmbeddingService(ABC):
    name: str
    model_name: str

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Length of every vector this service produces (the Qdrant vector size)."""

    @property
    def is_ready(self) -> bool:
        return True

    def warm_up(self) -> None:
        """Load anything slow ahead of the first request. Must not raise."""

    @abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """One vector per text, in order."""

    def embed_text(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


class LocalEmbeddingService(EmbeddingService):
    """A sentence-transformers model run locally as ONNX (fastembed).

    No API key or network after the first download; the model is cached in
    EMBEDDING_CACHE_DIR (a Docker volume in compose).
    """

    name = "local"

    def __init__(self, settings: Settings) -> None:
        self.model_name = settings.embedding_model
        self.cache_dir = settings.embedding_cache_dir
        self._model = None
        self._dimension: int | None = None
        self._lock = threading.Lock()

    def _get_model(self):
        if self._model is None:
            with self._lock:
                if self._model is None:
                    from fastembed import TextEmbedding

                    logger.info("Loading embedding model %s (first run downloads it)", self.model_name)
                    try:
                        self._model = TextEmbedding(model_name=self.model_name, cache_dir=self.cache_dir)
                    except Exception as exc:  # noqa: BLE001 - download/ONNX errors vary
                        logger.error("Could not load embedding model %s: %s", self.model_name, exc)
                        raise EmbeddingError("The embedding model is not available right now") from exc
                    logger.info("Embedding model ready")
        return self._model

    @property
    def dimension(self) -> int:
        if self._dimension is None:
            from fastembed import TextEmbedding

            try:
                self._dimension = TextEmbedding.get_embedding_size(self.model_name)
            except ValueError:
                # Not in fastembed's registry (custom model): measure it.
                self._dimension = len(self.embed_text("dimension probe"))
        return self._dimension

    @property
    def is_ready(self) -> bool:
        return self._model is not None

    def warm_up(self) -> None:
        try:
            self._get_model()
        except EmbeddingError:
            pass  # already logged; requests will report it

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._get_model()
        try:
            return [vector.tolist() for vector in model.embed(texts)]
        except Exception as exc:  # noqa: BLE001
            logger.error("Embedding failed for %d texts: %s", len(texts), exc)
            raise EmbeddingError("Could not create embeddings for this text") from exc


_PROVIDERS: dict[str, type[EmbeddingService]] = {
    "local": LocalEmbeddingService,
}


@lru_cache
def get_embedding_service() -> EmbeddingService:
    settings = get_settings()
    provider = _PROVIDERS.get(settings.embedding_provider.lower())
    if provider is None:
        raise EmbeddingError(f"Unknown EMBEDDING_PROVIDER '{settings.embedding_provider}'")
    return provider(settings)
