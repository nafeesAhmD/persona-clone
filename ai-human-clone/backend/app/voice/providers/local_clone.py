"""Free self-hosted voice cloning: the local Chatterbox Multilingual service.

The service runs next to the backend (docker compose profile "voice-clone", folder
voice-clone/) at LOCAL_VOICE_CLONE_URL, e.g. http://voice-clone:8100. Recordings and
text never leave this server. Cloned voices are addressed as "local:<voice_id>" (see
app/voice/routing.py).

Service API: POST /voices (multipart `files`, mono WAV) -> {"voice_id", "reference_seconds"};
DELETE /voices/{id}; POST /synthesize {"voice_id", "text" (1..1000), "language_id"} -> WAV.
Every call sends X-Service-Token when VOICE_CLONE_SERVICE_TOKEN is set. The model is
CPU-only and slow, so speech uses LOCAL_VOICE_CLONE_TIMEOUT_SECONDS, not VOICE_TIMEOUT_SECONDS.

Two services: LOCAL_VOICE_CLONE_URL may point at a fast GPU service (e.g. Google Colab,
see voice-clone/colab/) with LOCAL_VOICE_CLONE_FALLBACK_URL at the laptop one. Speech
goes to the first that answers; a new voice is stored on both under one id. GET /health
tells the engine: "omnivoice" speaks Urdu itself (sent in Urdu script as "ur"),
"chatterbox" reads Urdu from Devanagari as "hi".

The token, audio and text are never logged: only sizes and status codes.
"""

import io
import logging
import re
import time
import uuid

import av
import httpx
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.voice.audio import pcm_to_wav
from app.voice.base import (
    InvalidAudioError,
    SpeechAudio,
    TextToSpeechProvider,
    VoiceError,
    VoiceNotConfiguredError,
    VoiceOption,
    VoiceRateLimitError,
    VoiceTimeoutError,
    VoiceUnavailableError,
)
from app.voice.providers.elevenlabs import VoiceNotFoundError
from app.voice import pronounce
from app.voice.roman_urdu import is_roman_urdu, roman_urdu_to_devanagari
from app.voice.transliterate import has_arabic_script, urdu_to_devanagari

logger = logging.getLogger(__name__)

NAME = "local"
MODEL = "chatterbox-multilingual"
CLONE_TIMEOUT_SECONDS = 180.0
DELETE_TIMEOUT_SECONDS = 20.0
# The service takes 1..1000 characters per request; shorter pieces also sound steadier.
MAX_CHUNK_CHARACTERS = 400
PAUSE_SECONDS = 0.15
# Languages the model speaks (no Urdu: Urdu is spoken with "hi", see language_for).
LANGUAGES = frozenset(
    "ar da de el en es fi fr he hi it ja ko ms nl no pl pt ru sv sw tr zh".split()
)

NOT_CONFIGURED = "Voice cloning isn't set up on this server (the local voice-clone service)."
INVALID_SAMPLES = (
    "The voice service couldn't use these recordings. Record again in a quiet room, "
    "speaking naturally (one speaker only)."
)

_transport: httpx.BaseTransport | httpx.AsyncBaseTransport | None = None  # tests set httpx.MockTransport
_SENTENCE = re.compile(r"(?<=[.!?।۔؟])\s+")
_DEVANAGARI = re.compile("[ऀ-ॿ]")


class LocalCloneNotConfiguredError(VoiceNotConfiguredError):
    user_message = NOT_CONFIGURED


class LocalCloneLoadingError(VoiceUnavailableError):
    user_message = "The voice service is still starting (loading its voice model). Please try again in a minute."


class LocalCloneTooLargeError(InvalidAudioError):
    def __init__(self) -> None:
        super().__init__("The recordings are too large for the voice service. Use shorter recordings.", 413)


def configured() -> bool:
    return bool(get_settings().local_voice_clone_url)


def _require_url() -> str:
    url = get_settings().local_voice_clone_url
    if not url:
        raise LocalCloneNotConfiguredError("LOCAL_VOICE_CLONE_URL is not set")
    return url


def _urls() -> list[str]:
    """The service URLs in order: LOCAL_VOICE_CLONE_URL, then the fallback if it differs."""
    urls = [_require_url(), get_settings().local_voice_clone_fallback_url or ""]
    return list(dict.fromkeys(url.rstrip("/") for url in urls if url))


def _common(timeout: float, url: str | None = None) -> dict:
    settings = get_settings()
    headers = {"X-Service-Token": settings.voice_clone_service_token} if settings.voice_clone_service_token else {}
    return {
        "base_url": (url or _require_url()).rstrip("/"),
        "headers": headers,
        "timeout": httpx.Timeout(timeout, connect=min(10.0, timeout)),
        "transport": _transport,
    }


ENGINE_CACHE_SECONDS = 300.0
_engines: dict[str, tuple[str, float]] = {}  # url -> (engine name, expires at)


async def _engine(url: str) -> str:
    """The service's engine from GET /health ("chatterbox" when it doesn't say or can't be asked)."""
    known = _engines.get(url)
    if known and known[1] > time.monotonic():
        return known[0]
    try:
        async with httpx.AsyncClient(**_common(10.0, url)) as client:
            response = await client.get("/health")
        name = str(response.json().get("engine") or "chatterbox") if response.status_code == 200 else None
    except (httpx.HTTPError, ValueError, AttributeError):
        name = None
    if name is None:
        return "chatterbox"  # not cached: ask again next time
    _engines[url] = (name, time.monotonic() + ENGINE_CACHE_SECONDS)
    return name


def reset_engine_cache() -> None:
    _engines.clear()


def _check(response: httpx.Response, what: str) -> None:
    """Map a service error status to a VoiceError with a safe user message."""
    code = response.status_code
    if code < 400:
        return
    detail = f"Local voice-clone {what} returned {code}"  # never the body
    if code in (401, 403):
        raise LocalCloneNotConfiguredError(f"{detail} (VOICE_CLONE_SERVICE_TOKEN rejected)")
    if code == 404:
        raise VoiceNotFoundError(detail)
    if code == 413:
        if what == "voice clone":
            raise LocalCloneTooLargeError()
        raise VoiceError(detail)
    if code in (400, 422):
        if what == "voice clone":
            raise InvalidAudioError(INVALID_SAMPLES)
        raise VoiceError(detail)
    if code == 429:
        raise VoiceRateLimitError(detail)
    if code == 503:
        raise LocalCloneLoadingError(f"{detail} (model loading or busy)")
    if code == 504:
        raise VoiceTimeoutError(detail)
    raise VoiceUnavailableError(detail)


def language_for(text: str, language: str | None) -> tuple[str, str]:
    """(text to send, language_id) for the model.

    Urdu in Arabic script and Roman Urdu (Urdu in Latin letters) are rewritten in
    Devanagari and spoken as Hindi ("hi"); other supported languages pass through, and
    other Latin text is English.
    """
    lang = (language or "").split("-")[0].strip().lower()
    if has_arabic_script(text) and lang != "ar":
        return urdu_to_devanagari(text), "hi"
    if lang in LANGUAGES and lang not in ("en", "hi"):
        return text, lang
    if is_roman_urdu(text, expected=lang in ("ur", "hi")):
        return roman_urdu_to_devanagari(text), "hi"
    if lang in LANGUAGES:
        return text, lang
    return text, "en"  # unknown or unsupported


def segments(text: str, language: str | None) -> list[tuple[str, str]]:
    """[(text to send, language_id)] in order: like language_for, but when the text mixes
    Roman Urdu and English each sentence keeps its own language ("Hello! Aap kaise hain?")."""
    lang = (language or "").split("-")[0].strip().lower()
    whole = language_for(text, language)
    if whole[1] != "hi" or has_arabic_script(text) or not is_roman_urdu(text, expected=lang in ("ur", "hi")):
        return [whole]
    result: list[tuple[str, str]] = []
    for sentence in _SENTENCE.split(text.strip()):
        if not sentence:
            continue
        if is_roman_urdu(sentence, expected=True):
            spoken, language_id = roman_urdu_to_devanagari(sentence), "hi"
        else:
            spoken, language_id = sentence, "en"
        if result and result[-1][1] == language_id:
            result[-1] = (f"{result[-1][0]} {spoken}", language_id)
        else:
            result.append((spoken, language_id))
    return result


def script_segments(text: str) -> list[tuple[str, str]]:
    """Sentences with Devanagari are Hindi ("hi"), the rest English; neighbours are merged."""
    result: list[tuple[str, str]] = []
    for sentence in _SENTENCE.split(text.strip()):
        if not sentence:
            continue
        language_id = "hi" if _DEVANAGARI.search(sentence) else "en"
        if result and result[-1][1] == language_id:
            result[-1] = (f"{result[-1][0]} {sentence}", language_id)
        else:
            result.append((sentence, language_id))
    return result


def urdu_script_segments(text: str, other: str = "en") -> list[tuple[str, str]]:
    """Sentences in Urdu script are Urdu ("ur"), the rest `other`; neighbours are merged."""
    result: list[tuple[str, str]] = []
    for sentence in _SENTENCE.split(text.strip()):
        if not sentence:
            continue
        language_id = "ur" if has_arabic_script(sentence) else other
        if result and result[-1][1] == language_id:
            result[-1] = (f"{result[-1][0]} {sentence}", language_id)
        else:
            result.append((sentence, language_id))
    return result


async def native_urdu_segments(text: str, language: str | None) -> list[tuple[str, str]]:
    """For an engine that speaks Urdu (OmniVoice): Urdu goes in Urdu script as "ur"."""
    lang = (language or "").split("-")[0].strip().lower()
    if has_arabic_script(text) and lang != "ar":
        return urdu_script_segments(text)
    if lang and lang not in ("en", "hi", "ur"):
        return [(text, lang)]
    if _DEVANAGARI.search(text) or not is_roman_urdu(text, expected=lang in ("ur", "hi")):
        return segments(text, language)
    written = await pronounce.to_urdu_script(text)
    return urdu_script_segments(written) if written else segments(text, language)


async def spoken_segments(text: str, language: str | None, native_urdu: bool = False) -> list[tuple[str, str]]:
    """segments(), but Urdu is spelled by Gemini when it can (see pronounce.py): in Urdu script
    for an engine that speaks Urdu (`native_urdu`), otherwise in Devanagari."""
    if native_urdu:
        return await native_urdu_segments(text, language)
    by_rules = segments(text, language)
    if not any(language_id == "hi" for _, language_id in by_rules) or _DEVANAGARI.search(text):
        return by_rules  # no Urdu, or already in Devanagari
    written = await pronounce.to_devanagari(text)
    return script_segments(written) if written else by_rules


def chunks(text: str, limit: int = MAX_CHUNK_CHARACTERS) -> list[str]:
    """Split at sentence ends (then spaces) into pieces of at most `limit` characters."""
    pieces: list[str] = []
    current = ""
    for sentence in _SENTENCE.split(text.strip()):
        while len(sentence) > limit:
            cut = sentence.rfind(" ", 0, limit)
            cut = cut if cut > 0 else limit
            if current:
                pieces.append(current)
                current = ""
            pieces.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if current and len(current) + 1 + len(sentence) > limit:
            pieces.append(current)
            current = ""
        current = f"{current} {sentence}".strip() if current else sentence
    if current:
        pieces.append(current)
    return [piece for piece in pieces if piece]


def _join_wavs(parts: list[bytes]) -> bytes:
    """One mono 16-bit WAV from several WAVs (any PCM/float WAV PyAV can read)."""
    if len(parts) == 1:
        return parts[0]
    pcm = bytearray()
    rate = None
    for part in parts:
        with av.open(io.BytesIO(part), mode="r") as source:
            rate = rate or source.streams.audio[0].rate or 24_000
            resampler = av.AudioResampler(format="s16", layout="mono", rate=rate)
            for frame in source.decode(audio=0):
                for converted in resampler.resample(frame):
                    pcm += bytes(converted.planes[0])[: converted.samples * 2]
            for converted in resampler.resample(None):
                pcm += bytes(converted.planes[0])[: converted.samples * 2]
        pcm += b"\x00\x00" * int(rate * PAUSE_SECONDS)
    return pcm_to_wav(bytes(pcm), rate)


class LocalVoiceClone(TextToSpeechProvider):
    """Clone, speak with and delete personal voices at the local Chatterbox service."""

    name = NAME

    def voices(self) -> list[VoiceOption]:
        return []  # cloned voices belong to one clone each; see voice_clone_service

    async def clone_voice(
        self, name: str, files: list[tuple[str, bytes, str]], remove_background_noise: bool = False
    ) -> str:
        """Create a voice from `files` [(filename, mono WAV bytes, "audio/wav")]; returns its id.
        `name` and `remove_background_noise` are not used by the local service."""
        upload = [("files", (filename, data, mime)) for filename, data, mime in files]
        voice_id: str | None = None
        failure: VoiceError | None = None
        for index, url in enumerate(_urls()):
            # Every service stores the voice under the same id, so either can speak with it.
            try:
                created = await self._clone_at(url, upload, voice_id or uuid.uuid4().hex)
            except (VoiceUnavailableError, VoiceTimeoutError) as exc:
                logger.warning("Voice service %d could not store the voice (%s)", index + 1, type(exc).__name__)
                failure = failure or exc
                continue
            voice_id = voice_id or created
        if voice_id is None:
            raise failure or VoiceUnavailableError("No local voice-clone service")
        logger.info("Created a local voice clone from %d file(s)", len(files))
        await self.sync_transcript(voice_id)
        return voice_id

    async def sync_transcript(self, voice_id: str, language_hint: str | None = None) -> bool:
        """Give every service the text of the voice's reference, written by our own speech-to-text.
        OmniVoice needs it, and a wrong one (its Whisper guess at Urdu) makes it sound like
        someone still learning the language. Best effort: never fails the caller."""
        from app.voice.speech_to_text import transcribe_audio  # noqa: PLC0415 - avoids an import cycle

        urls = _urls()
        reference: bytes | None = None
        for url in urls:
            try:
                async with httpx.AsyncClient(**_common(CLONE_TIMEOUT_SECONDS, url)) as client:
                    response = await client.get(f"/voices/{voice_id}/reference")
            except httpx.HTTPError:
                continue
            if response.status_code == 200 and response.content:
                reference = response.content
                break
        if reference is None:
            return False  # an older service without the endpoint, or none reachable
        try:
            heard = await transcribe_audio(reference, "reference.wav", "audio/wav", language_hint=language_hint)
        except VoiceError as exc:
            logger.warning("Could not transcribe a voice reference (%s)", type(exc).__name__)
            return False
        stored = False
        for index, url in enumerate(urls):
            try:
                async with httpx.AsyncClient(**_common(CLONE_TIMEOUT_SECONDS, url)) as client:
                    response = await client.put(f"/voices/{voice_id}/transcript", json={"text": heard.text})
                stored = stored or response.status_code == 204
            except httpx.HTTPError as exc:
                logger.warning("Voice service %d did not take the transcript (%s)", index + 1, type(exc).__name__)
        return stored

    async def _clone_at(self, url: str, upload: list, chosen_id: str) -> str:
        try:
            async with httpx.AsyncClient(**_common(CLONE_TIMEOUT_SECONDS, url)) as client:
                response = await client.post("/voices", files=upload, data={"voice_id": chosen_id})
        except httpx.TimeoutException as exc:
            raise VoiceTimeoutError("Local voice clone timed out") from exc
        except httpx.HTTPError as exc:
            raise VoiceUnavailableError(f"Local voice-clone service unreachable ({type(exc).__name__})") from exc
        _check(response, "voice clone")
        try:
            voice_id = response.json().get("voice_id")
        except ValueError:
            voice_id = None
        if not voice_id or not re.fullmatch(r"[0-9a-fA-F]{8,64}", str(voice_id)):
            raise VoiceUnavailableError("Local voice-clone service returned no valid voice_id")
        return str(voice_id)

    async def synthesize(self, text: str, voice: str, language: str | None = None) -> SpeechAudio:
        """Speak at the first service that can: a GPU service that is off, unreachable
        (connect timeout) or without the voice hands over to the fallback. A timeout while
        speaking does not: the service is up and slow, the fallback would only wait again."""
        urls = _urls()
        for index, url in enumerate(urls):
            try:
                return await self._synthesize_at(url, text, voice, language)
            except (VoiceUnavailableError, VoiceNotFoundError, LocalCloneNotConfiguredError) as exc:
                if index == len(urls) - 1:
                    raise
                logger.warning("Voice service %d failed (%s); using the fallback", index + 1, type(exc).__name__)
        raise VoiceUnavailableError("No local voice-clone service")  # pragma: no cover - _urls() is never empty

    async def _synthesize_at(self, url: str, text: str, voice: str, language: str | None) -> SpeechAudio:
        native_urdu = await _engine(url) == "omnivoice"
        pieces = [
            (piece, language_id)
            for spoken, language_id in await spoken_segments(text, language, native_urdu)
            for piece in chunks(spoken)
        ]
        if not pieces:
            raise VoiceError("Nothing to speak")
        parts: list[bytes] = []
        try:
            async with httpx.AsyncClient(**_common(get_settings().local_voice_clone_timeout_seconds, url)) as client:
                for piece, language_id in pieces:
                    response = await client.post(
                        "/synthesize", json={"voice_id": voice, "text": piece, "language_id": language_id}
                    )
                    _check(response, "speech")
                    if not response.content:
                        raise VoiceUnavailableError("Local voice-clone service returned no audio")
                    parts.append(response.content)
        except httpx.ConnectTimeout as exc:
            # Never connected (e.g. a Colab tunnel that is gone): the same as "unreachable".
            raise VoiceUnavailableError("Local voice-clone service unreachable (ConnectTimeout)") from exc
        except httpx.TimeoutException as exc:
            raise VoiceTimeoutError("Local voice-clone speech timed out") from exc
        except httpx.HTTPError as exc:
            raise VoiceUnavailableError(f"Local voice-clone service unreachable ({type(exc).__name__})") from exc
        try:
            data = await run_in_threadpool(_join_wavs, parts)
        except Exception as exc:  # noqa: BLE001 - never echo decoder errors
            raise VoiceUnavailableError(f"Local voice-clone audio unreadable ({type(exc).__name__})") from exc
        languages = ",".join(sorted({language_id for _, language_id in pieces}))
        logger.info("Local voice clone spoke %d piece(s) in %s (%d bytes)", len(pieces), languages, len(data))
        return SpeechAudio(data=data, mime_type="audio/wav")

    def delete_voice(self, voice_id: str) -> None:
        """Delete a cloned voice everywhere. A voice that is already gone (404) counts as
        deleted. Every service is tried; if any could not delete it (e.g. a GPU service that
        is off still has a copy), this raises after trying the rest, so the caller can keep
        the delete pending and retry it (a withdrawn voice must not survive anywhere)."""
        failure: VoiceError | None = None
        for index, url in enumerate(_urls()):
            try:
                self._delete_at(url, voice_id)
            except (VoiceUnavailableError, VoiceTimeoutError) as exc:
                logger.warning("Voice service %d could not delete the voice (%s)", index + 1, type(exc).__name__)
                failure = failure or exc
        if failure:
            raise failure
        logger.info("Deleted a local voice clone")

    def _delete_at(self, url: str, voice_id: str) -> None:
        try:
            with httpx.Client(**_common(DELETE_TIMEOUT_SECONDS, url)) as client:
                response = client.delete(f"/voices/{voice_id}")
        except httpx.TimeoutException as exc:
            raise VoiceTimeoutError("Local voice delete timed out") from exc
        except httpx.HTTPError as exc:
            raise VoiceUnavailableError(f"Local voice-clone service unreachable ({type(exc).__name__})") from exc
        if response.status_code == 404:
            return
        _check(response, "voice delete")


def get_provider() -> LocalVoiceClone:
    """The local service client. Raises LocalCloneNotConfiguredError (503) without a URL."""
    _require_url()
    return LocalVoiceClone()
