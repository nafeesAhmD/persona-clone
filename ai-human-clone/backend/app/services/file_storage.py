"""Storage for uploaded knowledge files.

Files are addressed by (clone_id, stored_filename), where stored_filename is
generated here ("<32 hex chars>.<ext>"). User-supplied filenames never touch the
filesystem, so "../" tricks, odd characters and name collisions can't happen.

LocalFileStorage writes to disk; another backend (e.g. S3-compatible object
storage) only needs to implement the same FileStorage methods.
"""

import logging
import re
import shutil
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from typing import BinaryIO

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_STORED_NAME = re.compile(r"^[0-9a-f]{32}\.(pdf|docx|txt|md)$")
_CHUNK_SIZE = 1024 * 1024


class StorageError(Exception):
    """The file couldn't be written or read."""


class FileTooLargeError(Exception):
    """The upload exceeded the configured size limit (mapped to HTTP 413)."""


class FileStorage(ABC):
    @abstractmethod
    def save(self, clone_id: uuid.UUID, source: BinaryIO, extension: str, max_bytes: int) -> tuple[str, int]:
        """Store a stream; return (stored_filename, size in bytes). Raises FileTooLargeError."""

    @abstractmethod
    def local_path(self, clone_id: uuid.UUID, stored_filename: str) -> Path:
        """A readable local path for the stored file (extractors work on files)."""

    @abstractmethod
    def delete(self, clone_id: uuid.UUID, stored_filename: str) -> None: ...

    @abstractmethod
    def delete_clone(self, clone_id: uuid.UUID) -> None:
        """Remove every file stored for a clone."""


class LocalFileStorage(FileStorage):
    """storage/clones/{clone_id}/documents/{stored_filename}"""

    def __init__(self, base_dir: str | Path) -> None:
        self.base_dir = Path(base_dir).resolve()

    def _clone_dir(self, clone_id: uuid.UUID) -> Path:
        # uuid.UUID() rejects anything that isn't a UUID, so the path segment is safe.
        return self.base_dir / "clones" / str(uuid.UUID(str(clone_id))) / "documents"

    def _path(self, clone_id: uuid.UUID, stored_filename: str) -> Path:
        if not _STORED_NAME.fullmatch(stored_filename):
            raise StorageError("Invalid stored filename")
        path = (self._clone_dir(clone_id) / stored_filename).resolve()
        if not path.is_relative_to(self.base_dir):  # defence in depth
            raise StorageError("Path escapes the storage directory")
        return path

    def save(self, clone_id: uuid.UUID, source: BinaryIO, extension: str, max_bytes: int) -> tuple[str, int]:
        stored_filename = f"{uuid.uuid4().hex}.{extension}"
        final_path = self._path(clone_id, stored_filename)
        final_path.parent.mkdir(parents=True, exist_ok=True)
        partial = final_path.with_name(final_path.name + ".part")

        size = 0
        try:
            with partial.open("wb") as target:
                # Copy in chunks and stop as soon as the limit is passed.
                while chunk := source.read(_CHUNK_SIZE):
                    size += len(chunk)
                    if size > max_bytes:
                        raise FileTooLargeError
                    target.write(chunk)
            partial.replace(final_path)
        except FileTooLargeError:
            partial.unlink(missing_ok=True)
            raise
        except OSError as exc:
            partial.unlink(missing_ok=True)
            logger.error("Could not store upload for clone %s: %s", clone_id, exc)
            raise StorageError("Could not store the file") from exc
        return stored_filename, size

    def local_path(self, clone_id: uuid.UUID, stored_filename: str) -> Path:
        path = self._path(clone_id, stored_filename)
        if not path.is_file():
            raise StorageError("The stored file is missing")
        return path

    def delete(self, clone_id: uuid.UUID, stored_filename: str) -> None:
        try:
            self._path(clone_id, stored_filename).unlink(missing_ok=True)
        except (OSError, StorageError) as exc:
            logger.warning("Could not delete stored file %s: %s", stored_filename, exc)

    def delete_clone(self, clone_id: uuid.UUID) -> None:
        clone_dir = self._clone_dir(clone_id).parent  # storage/clones/{clone_id}
        if clone_dir.is_relative_to(self.base_dir) and clone_dir.exists():
            shutil.rmtree(clone_dir, ignore_errors=True)


def get_file_storage() -> FileStorage:
    # Built per call (cheap) so a changed UPLOAD_DIR, e.g. in tests, takes effect.
    return LocalFileStorage(get_settings().upload_dir)
