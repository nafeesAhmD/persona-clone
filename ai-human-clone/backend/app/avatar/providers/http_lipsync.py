"""Lip-sync on an external server (e.g. Wav2Lip, SadTalker or MuseTalk on a GPU machine).

Contract (easy to wrap around any open-source model):
    POST LIPSYNC_API_URL  (multipart: image=PNG, audio=MP3, fields fps, max_seconds)
    Authorization: Bearer LIPSYNC_API_KEY   (if set)
    -> 200 with the MP4 video as the body
The result is checked (real MP4, within MAX_VIDEO_DURATION_SECONDS) before it is kept.
"""

import logging

import av
import httpx

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


class HttpLipSync(LipSyncProvider):
    name = "http"

    def __init__(self, url: str | None, api_key: str | None, timeout_seconds: float, transport=None) -> None:
        self.url = url
        self.api_key = api_key
        self.timeout = timeout_seconds
        self._transport = transport  # tests pass a mock transport

    def render(self, request: LipSyncRequest, progress: ProgressCallback) -> float:
        if not self.url:
            raise LipSyncNotConfiguredError("LIPSYNC_API_URL is not set")
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        progress(20)
        try:
            with httpx.Client(timeout=self.timeout, transport=self._transport) as client:
                response = client.post(
                    self.url,
                    headers=headers,
                    files={
                        "image": ("avatar.png", request.image_path.read_bytes(), "image/png"),
                        "audio": (request.audio_path.name, request.audio_path.read_bytes(), "audio/mpeg"),
                    },
                    data={"fps": str(request.fps), "max_seconds": str(request.max_seconds)},
                )
        except httpx.TimeoutException as exc:
            raise LipSyncTimeoutError("The lip-sync server timed out") from exc
        except httpx.HTTPError as exc:
            raise LipSyncUnavailableError("Could not reach the lip-sync server") from exc
        if response.status_code in (401, 403):
            raise LipSyncNotConfiguredError(f"The lip-sync server rejected the key ({response.status_code})")
        if response.status_code == 429 or response.status_code >= 500:
            raise LipSyncUnavailableError(f"The lip-sync server returned {response.status_code}")
        if response.status_code != 200 or response.content[4:8] != b"ftyp":
            raise AvatarError(f"The lip-sync server returned no MP4 ({response.status_code})")
        progress(85)
        request.output_path.write_bytes(response.content)
        try:
            with av.open(str(request.output_path)) as container:
                duration = (container.duration or 0) / 1_000_000
                if not container.streams.video:
                    raise AvatarError("The lip-sync video has no picture")
        except AvatarError:
            request.output_path.unlink(missing_ok=True)
            raise
        except Exception as exc:  # noqa: BLE001
            request.output_path.unlink(missing_ok=True)
            raise AvatarError("The lip-sync server returned an unreadable video") from exc
        if duration > request.max_seconds + 1:
            request.output_path.unlink(missing_ok=True)
            raise AvatarError("The lip-sync video is longer than allowed")
        return round(duration, 2)
