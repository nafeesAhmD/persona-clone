"""Voice clone service: internal HTTP API around Chatterbox Multilingual.

Endpoints (JSON errors as {"detail": ...}):
  GET    /health                 -> {"status", "model_loaded", "device"}
  POST   /voices                 multipart "files" -> 201 {"voice_id", "reference_seconds"}
  DELETE /voices/{voice_id}      -> 204
  POST   /synthesize             {"voice_id", "text", "language_id"} -> audio/wav

Logs carry sizes and timings only; request text is never logged.
"""

from __future__ import annotations

import asyncio
import hmac
import logging
import os
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from audio import REFERENCE_SAMPLE_RATE, AudioError, build_reference, decode_audio, encode_wav
from model import (
    SUPPORTED_LANGUAGES,
    Engine,
    ModelManager,
    ModelNotReady,
    SynthesisCancelled,
    engine_class,
)

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("voice_clone")

VOICE_ID_RE = re.compile(r"^[0-9a-f]{32}$")
LANGUAGE_RE = re.compile(r"^[a-z]{2,3}$")
# Files kept next to <voice_id>.wav: its transcript and OmniVoice's saved clone prompt.
VOICE_SIDECARS = (".txt", ".omnivoice.pt")
MAX_TEXT_CHARS = 1000
MAX_FILES = 20


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except ValueError:
        return default


class TranscriptRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class SynthesizeRequest(BaseModel):
    voice_id: str
    text: str = Field(min_length=1, max_length=MAX_TEXT_CHARS)
    language_id: str

    @field_validator("text")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text must not be blank")
        return value


class VoiceStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def path(self, voice_id: str) -> Path:
        if not VOICE_ID_RE.fullmatch(voice_id):
            raise HTTPException(status_code=400, detail="invalid voice_id")
        return self.directory / f"{voice_id}.wav"

    def save(self, voice_id: str, wav_bytes: bytes) -> None:
        target = self.path(voice_id)
        self.directory.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".tmp")
        tmp.write_bytes(wav_bytes)
        os.replace(tmp, target)


def create_app(
    engine_factory: Callable[[], Engine] | None = None,
    data_dir: str | os.PathLike | None = None,
) -> FastAPI:
    token = os.getenv("VOICE_CLONE_SERVICE_TOKEN", "")
    max_upload_bytes = int(_env_float("MAX_UPLOAD_MB", 50) * 1024 * 1024)
    synth_timeout = _env_float("SYNTH_TIMEOUT_SECONDS", 240)
    model_wait = _env_float("MODEL_WAIT_SECONDS", 30)
    max_queue = int(_env_float("MAX_QUEUED_SYNTHESES", 4))

    store = VoiceStore(Path(data_dir or os.getenv("VOICE_DATA_DIR", "/data/voices")))
    engine_factory = engine_factory or engine_class(os.getenv("VOICE_CLONE_ENGINE", "chatterbox"))
    engine_name = getattr(engine_factory, "name", "chatterbox")
    # None = any language code the engine knows (OmniVoice); otherwise a fixed set.
    languages = getattr(engine_factory, "languages", SUPPORTED_LANGUAGES)
    manager = ModelManager(engine_factory)
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="synth")
    queue_lock = threading.Lock()
    queued = {"count": 0}

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        manager.start_loading()
        yield
        executor.shutdown(wait=False, cancel_futures=True)

    app = FastAPI(title="Voice Clone Service", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.manager = manager
    app.state.store = store

    @app.middleware("http")
    async def guard(request: Request, call_next):
        if token and not (request.method == "GET" and request.url.path == "/health"):
            sent = request.headers.get("x-service-token", "")
            if not hmac.compare_digest(sent.encode(), token.encode()):
                return JSONResponse(status_code=401, content={"detail": "invalid service token"})
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > max_upload_bytes:
            return JSONResponse(status_code=413, content={"detail": "upload too large"})
        return await call_next(request)

    @app.get("/health")
    async def health():
        return {"status": "ok", "model_loaded": manager.loaded, "device": manager.device, "engine": engine_name}

    @app.post("/voices", status_code=201)
    async def create_voice(files: list[UploadFile] = File(...), voice_id: str | None = Form(None)):
        # A caller may choose the id, so the same voice can live on two services (GPU + laptop).
        if voice_id is not None and not VOICE_ID_RE.fullmatch(voice_id):
            raise HTTPException(status_code=400, detail="invalid voice_id")
        chosen_id = voice_id
        if len(files) > MAX_FILES:
            raise HTTPException(status_code=400, detail=f"at most {MAX_FILES} files")
        started = time.monotonic()
        blobs: list[bytes] = []
        total = 0
        for upload in files:
            data = await upload.read()
            total += len(data)
            if total > max_upload_bytes:
                raise HTTPException(status_code=413, detail="upload too large")
            blobs.append(data)

        def process() -> tuple[str, float]:
            clips = [decode_audio(blob) for blob in blobs]
            reference = build_reference(clips)
            voice_id = chosen_id or uuid.uuid4().hex
            store.save(voice_id, encode_wav(reference, REFERENCE_SAMPLE_RATE))
            return voice_id, reference.size / REFERENCE_SAMPLE_RATE

        try:
            voice_id, seconds = await run_in_threadpool(process)
        except AudioError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        logger.info(
            "voice created: %d file(s), %d bytes -> %.1fs reference in %.2fs",
            len(blobs), total, seconds, time.monotonic() - started,
        )
        return {"voice_id": voice_id, "reference_seconds": round(seconds, 2)}

    @app.delete("/voices/{voice_id}", status_code=204)
    async def delete_voice(voice_id: str):
        path = store.path(voice_id)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="voice not found")
        path.unlink(missing_ok=True)
        for suffix in VOICE_SIDECARS:
            path.with_suffix(suffix).unlink(missing_ok=True)
        manager.forget_voice(voice_id)
        logger.info("voice deleted")
        return Response(status_code=204)

    @app.get("/voices/{voice_id}/reference")
    async def voice_reference(voice_id: str):
        """The stored reference WAV, so the caller can transcribe it (OmniVoice needs the text)."""
        path = store.path(voice_id)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="voice not found")
        return Response(content=path.read_bytes(), media_type="audio/wav")

    @app.put("/voices/{voice_id}/transcript", status_code=204)
    async def set_transcript(voice_id: str, body: TranscriptRequest):
        """What is said in the reference. Replaces OmniVoice's own Whisper guess; the saved
        clone prompt is dropped so the next speech rebuilds it with this text."""
        path = store.path(voice_id)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="voice not found")
        path.with_suffix(".txt").write_text(body.text.strip(), encoding="utf-8")
        path.with_suffix(".omnivoice.pt").unlink(missing_ok=True)
        manager.forget_voice(voice_id)
        logger.info("voice transcript set (%d chars)", len(body.text))
        return Response(status_code=204)

    @app.post("/synthesize")
    async def synthesize(body: SynthesizeRequest):
        language_id = body.language_id.strip().lower()
        if not LANGUAGE_RE.fullmatch(language_id) or (languages is not None and language_id not in languages):
            raise HTTPException(status_code=400, detail="unsupported language_id")
        voice_path = store.path(body.voice_id)
        if not voice_path.is_file():
            raise HTTPException(status_code=404, detail="voice not found")
        if not await run_in_threadpool(manager.wait_ready, model_wait):
            raise HTTPException(status_code=503, detail="model loading")

        with queue_lock:
            if queued["count"] >= max_queue:
                raise HTTPException(status_code=503, detail="busy, try again later")
            queued["count"] += 1

        cancel = threading.Event()
        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(
            executor, manager.synthesize, body.text, language_id, body.voice_id, voice_path, cancel
        )

        def _release(_):
            with queue_lock:
                queued["count"] -= 1

        future.add_done_callback(_release)
        try:
            audio = await asyncio.wait_for(future, timeout=synth_timeout)
        except asyncio.TimeoutError as exc:
            cancel.set()
            logger.warning("synthesis timed out after %.0fs (%d chars)", synth_timeout, len(body.text))
            raise HTTPException(status_code=504, detail="synthesis timed out") from exc
        except SynthesisCancelled as exc:
            raise HTTPException(status_code=504, detail="synthesis timed out") from exc
        except ModelNotReady as exc:
            raise HTTPException(status_code=503, detail="model loading") from exc
        except Exception as exc:
            logger.error("synthesis failed: %s", type(exc).__name__)
            raise HTTPException(status_code=500, detail="synthesis failed") from exc

        if audio.size == 0:
            raise HTTPException(status_code=500, detail="synthesis produced no audio")
        wav = await run_in_threadpool(encode_wav, audio, manager.sample_rate)
        return Response(content=wav, media_type="audio/wav")

    return app


app = create_app()
