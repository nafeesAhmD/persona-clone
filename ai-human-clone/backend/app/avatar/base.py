"""Provider-independent avatar interfaces.

AvatarProvider creates avatar images (built-in illustrated avatars);
LipSyncProvider turns an avatar image + speech into a talking-avatar video.
Routes and services use them only through app/avatar/factory.py, so a
provider can be swapped with LIPSYNC_PROVIDER without touching the rest.
"""

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


class AvatarError(Exception):
    """Base error for avatar failures the API handles.

    `str(exc)` is technical detail for logs; `user_message` is safe to show.
    """

    status_code = 502
    user_message = "The avatar service had a problem. Please try again."


class InvalidImageError(AvatarError):
    status_code = 400

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.user_message = message
        self.status_code = status_code


class LipSyncNotConfiguredError(AvatarError):
    status_code = 503
    user_message = "Avatar videos are not available on this server right now."


class LipSyncUnavailableError(AvatarError):
    status_code = 503
    user_message = "The avatar video service is temporarily unavailable. Please try again shortly."


class LipSyncTimeoutError(AvatarError):
    status_code = 504
    user_message = "The avatar video took too long to generate."


@dataclass(frozen=True)
class MouthPosition:
    """Where the mouth is, as fractions of the image: x, y of its centre and its width."""

    x: float
    y: float
    width: float


@dataclass(frozen=True)
class AvatarImage:
    """A processed avatar image ready to store (PNG bytes) and animate."""

    png: bytes
    width: int
    height: int
    mouth: MouthPosition
    face_detected: bool
    faces_found: int = 0


@dataclass(frozen=True)
class LipSyncRequest:
    image_path: Path
    audio_path: Path
    output_path: Path
    mouth: MouthPosition
    face_detected: bool
    max_seconds: float
    fps: int


ProgressCallback = Callable[[int], None]  # 0..100


class LipSyncProvider(ABC):
    name: str

    @abstractmethod
    def render(self, request: LipSyncRequest, progress: ProgressCallback) -> float:
        """Write an MP4 (H.264 + AAC) to request.output_path; return its duration in seconds.

        Runs in a worker thread, so it may block. Raises AvatarError on failure.
        """


@dataclass(frozen=True)
class AvatarStyle:
    skin: str
    hair: str
    hair_style: str  # "short", "long", "bun", "none"
    background: str
    shirt: str


class AvatarProvider(ABC):
    name: str

    @abstractmethod
    def presets(self) -> dict[str, AvatarStyle]:
        """Ready-made avatars by id."""

    @abstractmethod
    def generate(self, style: AvatarStyle) -> AvatarImage:
        """Draw an avatar in this style."""
