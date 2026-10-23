"""Model wrapper: lazy background loading and serialized generation.

The real Chatterbox engine imports torch only inside ``load()``, so this
module (and the API) can be imported and tested without torch or weights.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Callable, Protocol

import numpy as np

from audio import split_sentences

logger = logging.getLogger("voice_clone.model")

SUPPORTED_LANGUAGES = frozenset(
    "ar da de el en es fi fr he hi it ja ko ms nl no pl pt ru sv sw tr zh".split()
)

SENTENCE_GAP_SECONDS = 0.15


class Engine(Protocol):
    sample_rate: int
    device: str

    def load(self) -> None: ...

    def generate(self, text: str, language_id: str, voice_id: str, voice_path: Path) -> np.ndarray:
        """Return mono float32 samples at ``sample_rate``."""
        ...

    def forget_voice(self, voice_id: str) -> None: ...


class SynthesisCancelled(Exception):
    """The request timed out; remaining sentences are skipped."""


class ModelNotReady(Exception):
    pass


def pick_device(setting: str, cuda_available: bool) -> str:
    """VOICE_CLONE_DEVICE: "auto" (default) uses an NVIDIA GPU when there is one
    (e.g. on Google Colab, many times faster), otherwise the CPU."""
    setting = (setting or "auto").strip().lower()
    if setting == "auto":
        return "cuda" if cuda_available else "cpu"
    if setting == "cuda" and not cuda_available:
        raise RuntimeError("VOICE_CLONE_DEVICE=cuda but no CUDA GPU is available")
    return setting


class ChatterboxEngine:
    """Chatterbox Multilingual (MIT). Every output carries a Perth watermark."""

    name = "chatterbox"
    languages: frozenset[str] | None = SUPPORTED_LANGUAGES
    device = "cpu"

    def __init__(self, conds_cache_size: int = 4) -> None:
        self._model = None
        self.sample_rate = 24_000
        self._conds: OrderedDict[str, object] = OrderedDict()
        self._conds_cache_size = conds_cache_size

    def load(self) -> None:
        import torch  # noqa: PLC0415 - heavy import on purpose deferred
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS  # noqa: PLC0415

        threads = int(os.getenv("TORCH_NUM_THREADS", "0") or 0)
        if threads > 0:
            torch.set_num_threads(threads)
        self.device = pick_device(os.getenv("VOICE_CLONE_DEVICE", "auto"), torch.cuda.is_available())
        self._model = ChatterboxMultilingualTTS.from_pretrained(device=self.device)
        self.sample_rate = int(self._model.sr)

    def _conditionals(self, voice_id: str, voice_path: Path):
        conds = self._conds.get(voice_id)
        if conds is not None:
            self._conds.move_to_end(voice_id)
            return conds
        self._model.prepare_conditionals(str(voice_path))
        conds = self._model.conds
        self._conds[voice_id] = conds
        while len(self._conds) > self._conds_cache_size:
            self._conds.popitem(last=False)
        return conds

    def generate(self, text: str, language_id: str, voice_id: str, voice_path: Path) -> np.ndarray:
        # Speaker conditionals are computed once per voice and reused for every
        # sentence instead of re-reading the reference on each generate() call.
        self._model.conds = self._conditionals(voice_id, voice_path)
        wav = self._model.generate(text, language_id=language_id)
        return wav.squeeze(0).detach().cpu().numpy().astype(np.float32)

    def forget_voice(self, voice_id: str) -> None:
        self._conds.pop(voice_id, None)


class OmniVoiceEngine:
    """OmniVoice (k2-fsa): 600+ languages including Urdu ("ur"). Meant for an NVIDIA GPU
    (e.g. Google Colab); far too slow on a laptop CPU. The weights are CC-BY-NC:
    personal / non-commercial use only.

    A voice needs the transcript of its reference: ``<voice_id>.txt`` next to the WAV if
    present, otherwise OmniVoice transcribes it with Whisper (downloaded on first use).
    The resulting clone prompt is saved as ``<voice_id>.omnivoice.pt`` and reused."""

    name = "omnivoice"
    languages: frozenset[str] | None = None  # any language code OmniVoice knows
    device = "cpu"

    def __init__(self, prompt_cache_size: int = 4) -> None:
        self._model = None
        self.sample_rate = 24_000
        self._prompts: OrderedDict[str, object] = OrderedDict()
        self._prompt_cache_size = prompt_cache_size
        self._config = None

    def load(self) -> None:
        import torch  # noqa: PLC0415 - heavy imports on purpose deferred
        from omnivoice import OmniVoice, OmniVoiceGenerationConfig  # noqa: PLC0415

        self.device = pick_device(os.getenv("VOICE_CLONE_DEVICE", "auto"), torch.cuda.is_available())
        on_gpu = self.device == "cuda"
        self._model = OmniVoice.from_pretrained(
            os.getenv("OMNIVOICE_MODEL", "k2-fsa/OmniVoice"),
            device_map="cuda:0" if on_gpu else "cpu",
            dtype=torch.float16 if on_gpu else torch.float32,
        )
        self.sample_rate = int(self._model.sampling_rate)
        self._config = OmniVoiceGenerationConfig(num_step=int(os.getenv("OMNIVOICE_STEPS", "32")))

    def _prompt(self, voice_id: str, voice_path: Path):
        from omnivoice import VoiceClonePrompt  # noqa: PLC0415

        prompt = self._prompts.get(voice_id)
        if prompt is not None:
            self._prompts.move_to_end(voice_id)
            return prompt
        saved = voice_path.with_suffix(".omnivoice.pt")
        if saved.is_file():
            prompt = VoiceClonePrompt.load(str(saved))
        else:
            transcript = voice_path.with_suffix(".txt")
            ref_text = transcript.read_text(encoding="utf-8").strip() if transcript.is_file() else None
            prompt = self._model.create_voice_clone_prompt(str(voice_path), ref_text=ref_text or None)
            try:
                prompt.save(str(saved))
            except OSError:
                logger.warning("could not save the voice prompt; it is rebuilt next time")
        self._prompts[voice_id] = prompt
        while len(self._prompts) > self._prompt_cache_size:
            self._prompts.popitem(last=False)
        return prompt

    def generate(self, text: str, language_id: str, voice_id: str, voice_path: Path) -> np.ndarray:
        audio = self._model.generate(
            text=text,
            language=language_id,
            voice_clone_prompt=self._prompt(voice_id, voice_path),
            generation_config=self._config,
        )[0]
        return np.asarray(audio, dtype=np.float32).reshape(-1)

    def forget_voice(self, voice_id: str) -> None:
        self._prompts.pop(voice_id, None)


ENGINES = {engine.name: engine for engine in (ChatterboxEngine, OmniVoiceEngine)}


def engine_class(name: str):
    """VOICE_CLONE_ENGINE: "chatterbox" (default, MIT) or "omnivoice" (GPU, non-commercial)."""
    key = (name or "chatterbox").strip().lower()
    if key not in ENGINES:
        raise ValueError(f"unknown VOICE_CLONE_ENGINE {name!r} (use: {', '.join(ENGINES)})")
    return ENGINES[key]


class ModelManager:
    """Loads the engine in a background thread and runs one generation at a time."""

    retry_initial_seconds = 15.0
    max_load_attempts = 1000

    def __init__(self, engine_factory: Callable[[], Engine]) -> None:
        self._engine_factory = engine_factory
        self._engine: Engine | None = None
        self._ready = threading.Event()
        self._loading = False
        self._state_lock = threading.Lock()
        self._generate_lock = threading.Lock()
        self.device = "cpu"

    # -- loading ---------------------------------------------------------------

    @property
    def loaded(self) -> bool:
        return self._ready.is_set()

    @property
    def sample_rate(self) -> int:
        return self._engine.sample_rate if self._engine else 24_000

    def start_loading(self) -> None:
        with self._state_lock:
            if self._ready.is_set() or self._loading:
                return
            self._loading = True
        threading.Thread(target=self._load, name="model-loader", daemon=True).start()

    def _load(self) -> None:
        # Retries with backoff: on a slow or flaky network the first-run weight
        # download (~3.2 GB) can fail part-way; huggingface_hub resumes it.
        delay = self.retry_initial_seconds
        attempt = 0
        try:
            while True:
                attempt += 1
                started = time.monotonic()
                logger.info("model loading started (attempt %d)", attempt)
                try:
                    engine = self._engine_factory()
                    engine.load()
                except Exception:
                    logger.exception(
                        "model failed to load after %.1fs; retrying in %.0fs",
                        time.monotonic() - started, delay,
                    )
                    if attempt >= self.max_load_attempts:
                        return
                    time.sleep(delay)
                    delay = min(delay * 2, 300.0)
                    continue
                self._engine = engine
                self.device = getattr(engine, "device", "cpu")
                self._ready.set()
                logger.info("model loaded in %.1fs", time.monotonic() - started)
                return
        finally:
            with self._state_lock:
                self._loading = False

    def wait_ready(self, timeout: float) -> bool:
        if self._ready.is_set():
            return True
        # A failed load is retried on demand.
        self.start_loading()
        return self._ready.wait(timeout)

    # -- generation --------------------------------------------------------------

    def forget_voice(self, voice_id: str) -> None:
        if self._engine is not None:
            with self._generate_lock:
                self._engine.forget_voice(voice_id)

    def synthesize(
        self,
        text: str,
        language_id: str,
        voice_id: str,
        voice_path: Path,
        cancel: threading.Event,
    ) -> np.ndarray:
        """Generate speech sentence by sentence; blocks, so call it from a worker thread."""
        if not self._ready.is_set() or self._engine is None:
            raise ModelNotReady()
        chunks = split_sentences(text)
        sr = self._engine.sample_rate
        gap = np.zeros(int(SENTENCE_GAP_SECONDS * sr), dtype=np.float32)
        parts: list[np.ndarray] = []
        started = time.monotonic()
        with self._generate_lock:
            for index, chunk in enumerate(chunks):
                if cancel.is_set():
                    raise SynthesisCancelled()
                t0 = time.monotonic()
                wav = self._engine.generate(chunk, language_id, voice_id, voice_path)
                logger.info(
                    "chunk %d/%d: %d chars -> %.2fs audio in %.2fs",
                    index + 1, len(chunks), len(chunk), wav.size / sr, time.monotonic() - t0,
                )
                if parts:
                    parts.append(gap)
                parts.append(np.asarray(wav, dtype=np.float32).reshape(-1))
        audio = np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)
        logger.info(
            "synthesized %d chars (%d chunks, lang=%s) -> %.2fs audio in %.2fs",
            len(text), len(chunks), language_id, audio.size / sr, time.monotonic() - started,
        )
        return audio
