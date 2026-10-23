"""Avatar images and generated videos on disk.

    storage/clones/{clone_id}/avatar/{32 hex}.png   (kept until deleted)
    storage/clones/{clone_id}/videos/{32 hex}.mp4   (deleted after VIDEO_RETENTION_HOURS)

Paths are built only from a validated UUID and a server-generated hex name,
so nothing from a request can point elsewhere. Deleting a clone removes its
whole folder (file_storage.delete_clone).
"""

import logging
import re
import time
import uuid
from pathlib import Path

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_NAME = re.compile(r"^[0-9a-f]{32}\.(png|mp4)$")


class AvatarStorageError(Exception):
    pass


class AvatarStorage:
    def __init__(self, base_dir: str | Path, video_retention_hours: float) -> None:
        self.base_dir = Path(base_dir).resolve()
        self.video_retention_seconds = video_retention_hours * 3600

    def _dir(self, clone_id: uuid.UUID, kind: str) -> Path:
        return self.base_dir / "clones" / str(uuid.UUID(str(clone_id))) / kind

    def path(self, clone_id: uuid.UUID, kind: str, name: str) -> Path:
        if kind not in ("avatar", "videos") or not _NAME.fullmatch(name or ""):
            raise AvatarStorageError("Invalid stored file name")
        path = (self._dir(clone_id, kind) / name).resolve()
        if not path.is_relative_to(self.base_dir):  # defence in depth
            raise AvatarStorageError("Path escapes the storage directory")
        return path

    def new_path(self, clone_id: uuid.UUID, kind: str) -> tuple[str, Path]:
        name = f"{uuid.uuid4().hex}.{'png' if kind == 'avatar' else 'mp4'}"
        path = self.path(clone_id, kind, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        return name, path

    def save_image(self, clone_id: uuid.UUID, png: bytes) -> str:
        name, path = self.new_path(clone_id, "avatar")
        try:
            path.write_bytes(png)
        except OSError as exc:
            raise AvatarStorageError("Could not store the avatar image") from exc
        return name

    def delete(self, clone_id: uuid.UUID, kind: str, name: str | None) -> None:
        if not name:
            return
        try:
            self.path(clone_id, kind, name).unlink(missing_ok=True)
        except (OSError, AvatarStorageError) as exc:
            logger.warning("Could not delete an avatar file: %s", type(exc).__name__)

    def video_if_fresh(self, clone_id: uuid.UUID, name: str | None) -> Path | None:
        """The video file if it exists and hasn't expired."""
        if not name:
            return None
        try:
            path = self.path(clone_id, "videos", name)
        except AvatarStorageError:
            return None
        if not path.is_file() or time.time() - path.stat().st_mtime > self.video_retention_seconds:
            return None
        return path

    def cleanup_videos(self) -> int:
        """Delete expired videos of every clone. Avatars and documents are never touched."""
        clones = self.base_dir / "clones"
        if not clones.is_dir():
            return 0
        cutoff = time.time() - self.video_retention_seconds
        removed = 0
        for videos in clones.glob("*/videos"):
            for path in videos.glob("*.mp4"):
                try:
                    if path.stat().st_mtime < cutoff:
                        path.unlink()
                        removed += 1
                except OSError as exc:
                    logger.warning("Could not remove an expired video: %s", exc)
            for partial in videos.glob("*.part"):
                if partial.stat().st_mtime < cutoff:
                    partial.unlink(missing_ok=True)
        if removed:
            logger.info("Removed %d expired avatar videos", removed)
        return removed


def get_avatar_storage() -> AvatarStorage:
    settings = get_settings()
    return AvatarStorage(settings.upload_dir, settings.video_retention_hours)
