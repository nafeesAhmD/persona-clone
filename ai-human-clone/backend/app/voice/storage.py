"""Temporary storage for generated speech.

Files live in {UPLOAD_DIR}/voice/{user_id}/{32 hex}.mp3 (or .wav). The path
is built only from a UUID and a server-generated hex id, both validated, so
request data can never point outside this directory. Only the user a file
was generated for can fetch it, and files expire after
VOICE_AUDIO_RETENTION_HOURS. Knowledge uploads ({UPLOAD_DIR}/clones) are
never touched here.
"""

import logging
import re
import time
import uuid
from pathlib import Path

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_AUDIO_ID = re.compile(r"^[0-9a-f]{32}$")
_EXTENSIONS = {"audio/mpeg": "mp3", "audio/wav": "wav"}
MIME_TYPES = {ext: mime for mime, ext in _EXTENSIONS.items()}


class VoiceAudioStore:
    def __init__(self, base_dir: str | Path, retention_hours: float) -> None:
        self.base_dir = (Path(base_dir) / "voice").resolve()
        self.retention_seconds = retention_hours * 3600

    def _user_dir(self, user_id: uuid.UUID) -> Path:
        return self.base_dir / str(uuid.UUID(str(user_id)))

    def save(self, user_id: uuid.UUID, data: bytes, mime_type: str, audio_id: str | None = None) -> str:
        """Store audio; `audio_id` (32 hex characters) is generated unless given."""
        audio_id = audio_id or uuid.uuid4().hex
        if not _AUDIO_ID.fullmatch(audio_id):
            raise ValueError("invalid audio id")
        directory = self._user_dir(user_id)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{audio_id}.{_EXTENSIONS.get(mime_type, 'mp3')}").write_bytes(data)
        return audio_id

    def find(self, user_id: uuid.UUID, audio_id: str) -> Path | None:
        """The user's unexpired file with this id, or None (bad id, someone else's, or expired)."""
        if not _AUDIO_ID.fullmatch(audio_id):
            return None
        directory = self._user_dir(user_id)
        for extension in MIME_TYPES:
            path = directory / f"{audio_id}.{extension}"
            if path.is_file() and path.resolve().parent == directory.resolve():
                if time.time() - path.stat().st_mtime > self.retention_seconds:
                    return None
                return path
        return None

    def cleanup(self) -> int:
        """Delete expired files and empty user folders. Returns how many files were removed."""
        if not self.base_dir.is_dir():
            return 0
        cutoff = time.time() - self.retention_seconds
        removed = 0
        for directory in self.base_dir.iterdir():
            if not directory.is_dir():
                continue
            for path in directory.iterdir():
                try:
                    if path.is_file() and path.suffix.lstrip(".") in MIME_TYPES and path.stat().st_mtime < cutoff:
                        path.unlink()
                        removed += 1
                except OSError as exc:
                    logger.warning("Could not remove expired voice file: %s", exc)
            try:
                directory.rmdir()  # only succeeds when empty
            except OSError:
                pass
        if removed:
            logger.info("Removed %d expired voice files", removed)
        return removed


def get_voice_store() -> VoiceAudioStore:
    settings = get_settings()
    return VoiceAudioStore(settings.upload_dir, settings.voice_audio_retention_hours)
