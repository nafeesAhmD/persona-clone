import os

# Settings are read once, so configure the environment before importing the app.
os.environ["JWT_SECRET_KEY"] = "test-secret-key-that-is-long-enough-for-hs256"
os.environ["COOKIE_SECURE"] = "false"

from collections.abc import Iterator  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app import models  # noqa: E402,F401
from app.db.base import Base  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402


import asyncio  # noqa: E402
import hashlib  # noqa: E402
import math  # noqa: E402
import re  # noqa: E402

from app.ai.base import LLMProvider  # noqa: E402
from app.ai.embedding_service import EmbeddingError, EmbeddingService  # noqa: E402
from app.ai.rag_context import NO_KNOWLEDGE  # noqa: E402
from app.services.qdrant_service import QdrantService  # noqa: E402


class FakeEmbeddingService(EmbeddingService):
    """Bag-of-words hashing vectors: texts sharing words are similar, like a real
    model but instant and offline. `fail` simulates an embedding outage."""

    name = "fake"
    model_name = "fake-bag-of-words"
    DIM = 256

    def __init__(self) -> None:
        self.fail = False
        self.calls = 0

    @property
    def dimension(self) -> int:
        return self.DIM

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if self.fail:
            raise EmbeddingError("Could not create embeddings for this text")
        self.calls += 1
        return [self._vector(text) for text in texts]

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self.DIM
        for word in re.findall(r"\w+", text.lower()):
            vector[int(hashlib.md5(word.encode()).hexdigest(), 16) % self.DIM] += 1.0
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]


@pytest.fixture(autouse=True)
def embeddings(monkeypatch) -> FakeEmbeddingService:
    fake = FakeEmbeddingService()
    monkeypatch.setattr("app.ai.embedding_service.get_embedding_service", lambda: fake)
    monkeypatch.setattr("app.api.routes.health.get_embedding_service", lambda: fake)
    return fake


class FakeLLM(LLMProvider):
    """Records every request; answers only from the knowledge it was given.

    If the reference knowledge has content, the reply repeats it (so tests can
    check grounding without depending on real model wording); otherwise it
    says it doesn't know. Set `error` to make the next call fail.
    """

    name = "fake"
    model = "fake-llm-1"

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.error: Exception | None = None
        self.delay = 0.0  # seconds to "think" before answering
        self.json_calls: list[dict] = []
        self.json_reply = '{"memories": []}'

    async def generate_response(self, system_prompt, user_message, context=None, history=None, options=None) -> str:
        self.calls.append(
            {
                "system": system_prompt,
                "message": user_message,
                "context": context,
                "history": list(history or []),
                "options": options,
            }
        )
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error is not None:
            raise self.error
        memories = re.findall(r"^\[Memory \d+\] \(\w+\) (.*)$", context or "", re.MULTILINE)
        facts = re.findall(r"Content:\n(.*?)(?=\n\n\[Knowledge Source|\Z)", context or "", re.DOTALL)
        parts = []
        if memories:
            parts.append("From my memory: " + " ".join(memories))
        if facts:
            parts.append("From my knowledge: " + " ".join(f.strip() for f in facts))
        if parts:
            return " ".join(parts)
        return "I don't have enough information in my current knowledge to answer that accurately."

    async def generate_json(self, system_prompt, user_message, schema) -> str:
        """Memory extraction: returns `json_reply` (set it in the test)."""
        self.json_calls.append({"system": system_prompt, "message": user_message, "schema": schema})
        if self.error is not None:
            raise self.error
        return self.json_reply

    async def check_connection(self) -> dict[str, object]:
        return {"provider": self.name, "configured": True, "reachable": True, "model": self.model}


@pytest.fixture(autouse=True)
def llm(monkeypatch) -> FakeLLM:
    fake = FakeLLM()
    monkeypatch.setattr("app.ai.factory.get_llm_provider", lambda: fake)
    return fake


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    from app.services.rate_limit import chat_limiter, voice_limiter

    chat_limiter.reset()
    voice_limiter.reset()
    from app.services.rate_limit import reset_public_limits

    reset_public_limits()
    yield
    chat_limiter.reset()
    voice_limiter.reset()


from app.voice.audio import pcm_to_wav  # noqa: E402
from app.voice.base import (  # noqa: E402
    SpeechAudio,
    SpeechToTextProvider,
    TextToSpeechProvider,
    Transcription,
    VoiceOption,
)


def tone_wav(seconds: float = 1.0, rate: int = 16_000) -> bytes:
    """A real WAV file: a 440 Hz tone."""
    samples = int(seconds * rate)
    pcm = b"".join(
        int(8000 * math.sin(2 * math.pi * 440 * i / rate)).to_bytes(2, "little", signed=True) for i in range(samples)
    )
    return pcm_to_wav(pcm, rate)


class FakeSTT(SpeechToTextProvider):
    """Returns `text` for any audio and records what it received."""

    name = "fake-stt"

    def __init__(self) -> None:
        self.text = "What technologies have I worked with?"
        self.language: str | None = "en"
        self.error: Exception | None = None
        self.calls: list[dict] = []

    async def transcribe(self, audio, language_hint=None):
        self.calls.append({"duration": audio.duration_seconds, "wav": audio.wav[:4], "hint": language_hint})
        if self.error is not None:
            raise self.error
        return Transcription(text=self.text, language=self.language)


class FakeTTS(TextToSpeechProvider):
    """Speaks every text as a short tone (a real WAV), records the requests."""

    name = "fake-tts"

    def __init__(self) -> None:
        self.error: Exception | None = None
        self.calls: list[dict] = []

    def voices(self):
        return [
            VoiceOption("alto", "Alto", "AI voice"),
            VoiceOption("bass", "Bass", "AI voice"),
            VoiceOption("custom-owner", "Owner's cloned voice", "Personalised", is_custom=True),
        ]

    async def synthesize(self, text, voice, language=None):
        self.calls.append({"text": text, "voice": voice, "language": language})
        if self.error is not None:
            raise self.error
        return SpeechAudio(data=tone_wav(0.5, 24_000), mime_type="audio/wav")


@pytest.fixture(autouse=True)
def stt(monkeypatch) -> FakeSTT:
    fake = FakeSTT()
    monkeypatch.setattr("app.voice.factory.get_stt_provider", lambda: fake)
    return fake


@pytest.fixture(autouse=True)
def tts(monkeypatch) -> FakeTTS:
    fake = FakeTTS()
    monkeypatch.setattr("app.voice.factory.get_tts_provider", lambda: fake)
    return fake


@pytest.fixture(autouse=True)
def qdrant(monkeypatch) -> QdrantService:
    """A real Qdrant engine running in-process (no server), fresh for each test."""
    service = QdrantService(url=":memory:", collection_name="clone_memories")
    monkeypatch.setattr("app.services.qdrant_service.get_qdrant_service", lambda: service)
    monkeypatch.setattr("app.api.routes.health.get_qdrant_service", lambda: service)
    return service


@pytest.fixture(autouse=True)
def storage_dir(monkeypatch, tmp_path):
    """Each test stores uploads in its own temporary directory."""
    from app.core.config import get_settings

    directory = tmp_path / "storage"
    monkeypatch.setattr(get_settings(), "upload_dir", str(directory))
    return directory


@pytest.fixture
def db_session() -> Iterator[Session]:
    # A fresh in-memory database per test; StaticPool keeps one shared connection.
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture(autouse=True)
def _stream_sessions_use_test_db(monkeypatch, db_session: Session):
    """Streaming chat saves replies in a fresh session; point it at the test database."""
    from contextlib import nullcontext

    monkeypatch.setattr("app.services.chat_service.SessionLocal", lambda: nullcontext(db_session))


@pytest.fixture(autouse=True)
def _avatar_jobs_run_inline(monkeypatch, db_session: Session):
    """Video jobs run right away, in the test database (no worker thread)."""
    from contextlib import nullcontext

    from app.avatar import jobs

    monkeypatch.setattr(jobs, "SessionLocal", lambda: nullcontext(db_session))
    monkeypatch.setattr(jobs, "submit", jobs.run_job)
    from app.services.rate_limit import avatar_video_limiter

    avatar_video_limiter.reset()


@pytest.fixture(autouse=True)
def _voice_deletions_use_test_db(monkeypatch, db_session: Session):
    """Pending voice deletions are recorded and retried in the test database."""
    from contextlib import nullcontext

    monkeypatch.setattr("app.services.voice_clone_service.SessionLocal", lambda: nullcontext(db_session))


@pytest.fixture(autouse=True)
def _monitoring_uses_test_db(monkeypatch, db_session: Session):
    """Phase 10: security/usage/error events are written at once, into the test database;
    platform switches start from their defaults in every test."""
    from contextlib import nullcontext

    from app.services import monitoring, platform_service

    monkeypatch.setattr(monitoring, "SessionLocal", lambda: nullcontext(db_session))
    monkeypatch.setattr(monitoring, "INLINE", True)
    monitoring.reset_dedupe()
    platform_service.invalidate()
    yield
    platform_service.invalidate()


@pytest.fixture(autouse=True)
def _reset_developer_limits():
    """Phase 14: API-key rate windows and cached plans start empty in every test."""
    from app.developer import limits, rate_limit

    rate_limit.reset()
    limits.reset_cache()
    yield


@pytest.fixture(autouse=True)
def _agent_runs_inline(monkeypatch, db_session: Session):
    """Phase 16: agent executions run right away in the request, in the test database."""
    from contextlib import nullcontext

    from app.agent import runner

    monkeypatch.setattr(runner, "SessionLocal", lambda: nullcontext(db_session))
    monkeypatch.setattr(runner, "INLINE", True)
    yield


def make_admin(db_session: Session, email: str) -> None:
    """Tests grant admin straight in the database: there is (deliberately) no API for it."""
    from sqlalchemy import select

    from app.models import User

    user = db_session.scalar(select(User).where(User.email == email.lower()))
    user.is_admin = True
    db_session.commit()


@pytest.fixture
def client(db_session: Session) -> Iterator[TestClient]:
    app.dependency_overrides[get_db] = lambda: db_session
    # Not used as a context manager, so startup tasks (model download) don't run.
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def make_client(db_session: Session):
    """Extra independent browsers (separate cookie jars) sharing the same database."""
    app.dependency_overrides[get_db] = lambda: db_session
    yield lambda: TestClient(app)
    app.dependency_overrides.clear()


USER = {
    "email": "Ayaan@Example.com",
    "username": "ayaan",
    "full_name": "Ayaan",
    "password": "StrongPassword123!",
}


@pytest.fixture
def registered(client: TestClient) -> dict:
    response = client.post("/api/auth/register", json=USER)
    assert response.status_code == 201, response.text
    return response.json()


def open_to_public(client, clone_id: str, *, voice: bool = False, visibility: str = "public") -> dict:
    """Phase 9: visitors need the owner to turn public chat (and public voice) on."""
    settings = {"visibility": visibility, "public_chat_enabled": True}
    if voice:
        settings["public_voice_enabled"] = True
    response = client.patch(f"/api/clones/{clone_id}/public-settings", json=settings)
    assert response.status_code == 200, response.text
    return response.json()
