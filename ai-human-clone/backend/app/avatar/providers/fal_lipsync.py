"""Photo-realistic talking-avatar videos from a cloud model on fal.ai (LIPSYNC_PROVIDER=fal).

The avatar photo and the answer's speech are sent to fal.ai, which animates the
real face (lips, and depending on the model also eyes and head) instead of
drawing a mouth. Owners are told this before they turn avatar videos on.

Flow (fal's HTTP queue API, no SDK):
    POST https://queue.fal.run/{FAL_LIPSYNC_MODEL}   Authorization: Key FAL_API_KEY
         -> {request_id, status_url, response_url, cancel_url}
    GET  status_url  until COMPLETED  (IN_QUEUE / IN_PROGRESS before that)
    GET  response_url -> {"video": {"url": ...}}  -> download the MP4
Inputs go as data URIs (a JPEG of the avatar and an MP3 cut to
MAX_VIDEO_DURATION_SECONDS, since billing is per second of video). The result is
checked like any other provider's (real MP4, picture, length) before it is kept.
The API key is only ever sent in the Authorization header, never logged.
"""

import base64
import io
import logging
import time
from dataclasses import dataclass

import av
import httpx
from PIL import Image

from app.avatar.base import (
    AvatarError,
    LipSyncNotConfiguredError,
    LipSyncProvider,
    LipSyncRequest,
    LipSyncTimeoutError,
    LipSyncUnavailableError,
    ProgressCallback,
)

logger = logging.getLogger(__name__)

QUEUE_URL = "https://queue.fal.run"
MAX_VIDEO_BYTES = 200 * 1024 * 1024
AUDIO_RATE = 24_000


@dataclass(frozen=True)
class ModelSpec:
    """How one fal model names its inputs."""

    image_field: str
    audio_field: str
    extra: dict


# Image + audio -> talking video models. Others can be added the same way.
MODELS: dict[str, ModelSpec] = {
    # Realistic face, lips, eyes and light head motion; any language. 480p/720p.
    "veed/fabric-1.0": ModelSpec("image_url", "audio_url", {}),
    "veed/fabric-1.0/fast": ModelSpec("image_url", "audio_url", {}),
    # Open-source SadTalker: cheaper, more "talking head" than lifelike.
    "fal-ai/sadtalker": ModelSpec(
        "source_image_url",
        "driven_audio_url",
        {"face_model_resolution": "512", "preprocess": "full", "still_mode": True, "face_enhancer": "gfpgan"},
    ),
    # Expressive full-frame animation; needs a short prompt.
    "fal-ai/infinitalk": ModelSpec(
        "image_url", "audio_url", {"prompt": "A person talking naturally to the camera, realistic, steady camera."}
    ),
}


def _data_uri(data: bytes, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def _jpeg(path) -> bytes:
    """The avatar as a high-quality JPEG (much smaller to upload than PNG)."""
    with Image.open(path) as image:
        buffer = io.BytesIO()
        image.convert("RGB").save(buffer, format="JPEG", quality=92)
        return buffer.getvalue()


def _speech_mp3(path, max_seconds: float) -> tuple[bytes, float]:
    """The speech as MP3, at most max_seconds long, and its length."""
    from app.avatar.providers.local_lipsync import load_audio
    from app.voice.audio import encode_mp3, pcm_to_wav

    samples = load_audio(path, max_seconds)
    seconds = samples.size / AUDIO_RATE
    if seconds < 0.1:
        raise AvatarError("The speech audio is empty")
    return encode_mp3(pcm_to_wav(samples.tobytes(), AUDIO_RATE)), seconds


class FalLipSync(LipSyncProvider):
    name = "fal"

    def __init__(
        self,
        api_key: str | None,
        model: str,
        resolution: str,
        timeout_seconds: float,
        poll_seconds: float = 2.0,
        transport=None,
    ) -> None:
        self.api_key = api_key
        self.model = model.strip().strip("/")
        self.resolution = resolution
        self.timeout = timeout_seconds
        self.poll_seconds = poll_seconds
        self._transport = transport  # tests pass a mock transport

    # --- helpers --------------------------------------------------------------------

    def _check(self, response: httpx.Response, what: str) -> None:
        code = response.status_code
        if code in (401, 403):
            raise LipSyncNotConfiguredError(f"fal.ai rejected the API key ({code})")
        if code == 402:
            raise LipSyncUnavailableError("fal.ai account has no credit left (402)")
        if code == 429 or code >= 500:
            raise LipSyncUnavailableError(f"fal.ai {what} returned {code}")
        if code == 422:
            raise AvatarError(f"fal.ai couldn't use the inputs (422): {response.text[:300]}")
        if code >= 400:
            raise AvatarError(f"fal.ai {what} returned {code}")

    def _payload(self, image: bytes, audio: bytes) -> dict:
        spec = MODELS.get(self.model, MODELS["veed/fabric-1.0"])
        payload = {
            spec.image_field: _data_uri(image, "image/jpeg"),
            spec.audio_field: _data_uri(audio, "audio/mpeg"),
            **spec.extra,
        }
        if self.model.startswith("veed/") or self.model == "fal-ai/infinitalk":
            payload["resolution"] = self.resolution
        return payload

    # --- render ---------------------------------------------------------------------

    def render(self, request: LipSyncRequest, progress: ProgressCallback) -> float:
        if not self.api_key:
            raise LipSyncNotConfiguredError("FAL_API_KEY is not set")
        if self.model not in MODELS:
            raise LipSyncNotConfiguredError(f"Unsupported FAL_LIPSYNC_MODEL '{self.model}'")
        image = _jpeg(request.image_path)
        audio, seconds = _speech_mp3(request.audio_path, request.max_seconds)
        headers = {"Authorization": f"Key {self.api_key}"}
        deadline = time.monotonic() + self.timeout
        progress(15)
        cancel_url = None
        try:
            with httpx.Client(timeout=60.0, transport=self._transport, headers=headers) as client:
                submitted = client.post(f"{QUEUE_URL}/{self.model}", json=self._payload(image, audio))
                self._check(submitted, "submit")
                job = submitted.json()
                status_url, response_url = job.get("status_url"), job.get("response_url")
                cancel_url = job.get("cancel_url")
                if not status_url or not response_url:
                    raise AvatarError("fal.ai didn't return a request to follow")
                logger.info("fal.ai lip-sync request %s submitted (%s, %.1fs audio)", job.get("request_id"), self.model, seconds)
                progress(25)

                # Wait for the video. Progress creeps from 25 to 80 while it renders.
                started = time.monotonic()
                while True:
                    if time.monotonic() > deadline:
                        raise LipSyncTimeoutError("fal.ai didn't finish within LIPSYNC_TIMEOUT_SECONDS")
                    status = client.get(status_url)
                    self._check(status, "status")
                    state = status.json().get("status")
                    if state == "COMPLETED":
                        break
                    if state not in ("IN_QUEUE", "IN_PROGRESS"):
                        raise AvatarError(f"fal.ai request ended with status {state!r}")
                    elapsed = time.monotonic() - started
                    progress(min(80, 25 + int(55 * elapsed / max(30.0, seconds * 6))))
                    time.sleep(self.poll_seconds)
                cancel_url = None  # finished: nothing to cancel

                result = client.get(response_url)
                self._check(result, "result")
                body = result.json()
                video_url = (body.get("video") or {}).get("url")
                if not video_url or not str(video_url).startswith("https://"):
                    detail = body.get("detail") if isinstance(body, dict) else None
                    raise AvatarError(f"fal.ai returned no video ({str(detail)[:200]})")
                progress(85)

                # The video file is on fal's CDN; it's public by URL, so no key is sent.
                with httpx.Client(timeout=120.0, transport=self._transport, follow_redirects=True) as cdn:
                    with cdn.stream("GET", video_url) as download:
                        if download.status_code != 200:
                            raise LipSyncUnavailableError(f"Couldn't download the fal.ai video ({download.status_code})")
                        size = 0
                        with request.output_path.open("wb") as out:
                            for chunk in download.iter_bytes():
                                size += len(chunk)
                                if size > MAX_VIDEO_BYTES:
                                    raise AvatarError("The fal.ai video is too large")
                                out.write(chunk)
        except httpx.TimeoutException as exc:
            request.output_path.unlink(missing_ok=True)
            raise LipSyncTimeoutError("fal.ai timed out") from exc
        except httpx.HTTPError as exc:
            request.output_path.unlink(missing_ok=True)
            raise LipSyncUnavailableError("Could not reach fal.ai") from exc
        except BaseException:
            request.output_path.unlink(missing_ok=True)
            raise
        finally:
            if cancel_url:  # stop paying for a request we gave up on
                try:
                    with httpx.Client(timeout=10.0, transport=self._transport, headers=headers) as client:
                        client.put(cancel_url)
                except httpx.HTTPError:
                    pass
        return self._verify(request)

    def _verify(self, request: LipSyncRequest) -> float:
        try:
            with request.output_path.open("rb") as file:
                if file.read(12)[4:8] != b"ftyp":
                    raise AvatarError("fal.ai returned something that isn't an MP4")
            with av.open(str(request.output_path)) as container:
                duration = (container.duration or 0) / 1_000_000
                if not container.streams.video:
                    raise AvatarError("The fal.ai video has no picture")
        except AvatarError:
            request.output_path.unlink(missing_ok=True)
            raise
        except Exception as exc:  # noqa: BLE001
            request.output_path.unlink(missing_ok=True)
            raise AvatarError("fal.ai returned an unreadable video") from exc
        if duration > request.max_seconds + 2:
            request.output_path.unlink(missing_ok=True)
            raise AvatarError("The fal.ai video is longer than allowed")
        logger.info("fal.ai talking-avatar video ready (%.1fs, %s)", duration, self.model)
        return round(duration, 2)
