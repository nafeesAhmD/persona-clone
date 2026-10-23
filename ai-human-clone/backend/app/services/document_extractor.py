"""File type detection and text extraction for knowledge uploads.

Only PDF, DOCX and plain text (.txt, plus .md for older uploads) are accepted.
The type is decided by the file's actual bytes, not only its name, and every
failure becomes an ExtractionError with a message that is safe to show users.
No OCR: scanned PDFs without a text layer fail with a clear message.
"""

import logging
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePath

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FileKind:
    file_type: str  # stored in documents.file_type
    mime_type: str


PDF = FileKind("pdf", "application/pdf")
DOCX = FileKind("docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
TXT = FileKind("txt", "text/plain")
MD = FileKind("md", "text/markdown")

EXTENSIONS = {".pdf": PDF, ".docx": DOCX, ".txt": TXT, ".md": MD}
SUPPORTED_LABEL = "PDF, DOCX or TXT"

# Content types browsers send for these files. application/octet-stream is common
# for any upload, so the real check is the byte sniffing below.
_ALLOWED_CLIENT_MIME = {
    "pdf": {"application/pdf", "application/x-pdf"},
    "docx": {DOCX.mime_type, "application/zip"},
    "txt": {"text/plain"},
    "md": {"text/markdown", "text/x-markdown", "text/plain"},
}
_GENERIC_MIME = {"", "application/octet-stream", "binary/octet-stream"}
_SNIFF_BYTES = 8192
_OCR_MESSAGE = "No extractable text found. OCR support is not enabled yet."


class UnsupportedFileError(ValueError):
    """Rejected before storing: wrong extension, wrong content, or empty."""


class ExtractionError(Exception):
    """Stored, but text couldn't be extracted. The message is safe to show."""


def kind_from_filename(filename: str) -> FileKind:
    kind = EXTENSIONS.get(PurePath(filename).suffix.lower())
    if kind is None:
        raise UnsupportedFileError(f"Unsupported file type. Upload a {SUPPORTED_LABEL} file.")
    return kind


def kind_for_type(file_type: str | None) -> FileKind:
    for kind in EXTENSIONS.values():
        if kind.file_type == file_type:
            return kind
    raise UnsupportedFileError("Unknown stored file type.")


def check_client_mime(kind: FileKind, content_type: str | None) -> None:
    mime = (content_type or "").split(";")[0].strip().lower()
    if mime not in _GENERIC_MIME and mime not in _ALLOWED_CLIENT_MIME[kind.file_type]:
        raise UnsupportedFileError(f"The file's content type ({mime}) doesn't match a .{kind.file_type} file.")


def verify_content(kind: FileKind, path: Path) -> None:
    """Make sure the bytes really are what the extension claims (no renamed executables)."""
    with path.open("rb") as handle:
        head = handle.read(_SNIFF_BYTES)
    if not head:
        raise UnsupportedFileError("The file is empty.")

    if kind is PDF:
        if b"%PDF-" not in head[:1024]:
            raise UnsupportedFileError("This file isn't a valid PDF.")
    elif kind is DOCX:
        if not head.startswith(b"PK\x03\x04"):
            raise UnsupportedFileError("This file isn't a valid DOCX document.")
        try:
            with zipfile.ZipFile(path) as archive:
                if "word/document.xml" not in archive.namelist():
                    raise UnsupportedFileError("This file isn't a valid DOCX document.")
        except zipfile.BadZipFile as exc:
            raise UnsupportedFileError("This file isn't a valid DOCX document.") from exc
    else:
        if b"\x00" in head or head.startswith((b"MZ", b"\x7fELF", b"PK\x03\x04", b"%PDF-")):
            raise UnsupportedFileError("This doesn't look like a plain text file.")


def normalize_text(text: str) -> str:
    """Tidy whitespace but keep paragraph breaks."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    text = text.replace(" ", " ")
    text = re.sub(r"[ \t\f\v]+", " ", text)  # runs of spaces/tabs -> one space
    text = re.sub(r" *\n *", "\n", text)  # no spaces around line breaks
    text = re.sub(r"\n{3,}", "\n\n", text)  # at most one blank line between paragraphs
    return text.strip()


def _extract_pdf(path: Path, max_pages: int) -> str:
    from pypdf import PdfReader

    reader = PdfReader(path)
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception as exc:  # noqa: BLE001 - any failure means we can't read it
            raise ExtractionError("This PDF is password-protected.") from exc
    if len(reader.pages) > max_pages:
        raise ExtractionError(f"This PDF has more than {max_pages} pages. Split it into smaller files.")
    return "\n\n".join(page.extract_text() or "" for page in reader.pages)


def _extract_docx(path: Path) -> str:
    import docx

    document = docx.Document(str(path))
    parts = [paragraph.text for paragraph in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            parts.append(" | ".join(cell.text.strip() for cell in row.cells))
    return "\n".join(parts)


def _extract_text_file(path: Path, max_characters: int) -> str:
    # Read at most ~4 bytes per allowed character; more than that is over the limit anyway.
    with path.open("rb") as handle:
        data = handle.read(max_characters * 4 + 1)
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def extract_text(path: Path, kind: FileKind, *, max_characters: int, max_pdf_pages: int) -> str:
    """Return normalised text, or raise ExtractionError with a user-safe message."""
    try:
        if kind is PDF:
            raw = _extract_pdf(path, max_pdf_pages)
        elif kind is DOCX:
            raw = _extract_docx(path)
        else:
            raw = _extract_text_file(path, max_characters)
    except ExtractionError:
        raise
    except Exception as exc:  # noqa: BLE001 - malformed files raise all kinds of errors
        logger.warning("Extraction failed for %s (%s): %s", path.name, kind.file_type, exc)
        raise ExtractionError(f"Could not read this {kind.file_type.upper()} file. It may be damaged.") from exc

    text = normalize_text(raw)
    if not text:
        raise ExtractionError(_OCR_MESSAGE if kind is PDF else "The file contains no text.")
    if len(text) > max_characters:
        raise ExtractionError(
            f"The document has more than {max_characters:,} characters of text. Split it into smaller files."
        )
    return text
