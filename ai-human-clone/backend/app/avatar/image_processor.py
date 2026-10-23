"""Avatar image validation, normalisation and mouth finding.

An upload is accepted only if its extension, declared MIME type and actual
bytes agree (JPEG, PNG or WebP), it is within MAX_AVATAR_SIZE_MB, and Pillow
can decode it (with a decompression-bomb limit). It is then re-encoded as a
fresh PNG, which drops EXIF/GPS and other metadata. Orientation is applied,
the long side is capped at MAX_SIDE and sides are made even (video encoders
need that); nothing is cropped.

The mouth is located with OpenCV's bundled face detector (CPU, no downloads).
If no face is found, a centred guess is used and the owner can correct it.
"""

import io
import logging
from functools import lru_cache
from pathlib import Path, PurePath

from PIL import Image, ImageOps, UnidentifiedImageError

from app.avatar.base import AvatarImage, InvalidImageError, MouthPosition
from app.core.config import get_settings

logger = logging.getLogger(__name__)

MAX_SIDE = 1024
MIN_SIDE = 128
MAX_PIXELS = 40_000_000  # decoding limit (decompression bombs)
DEFAULT_MOUTH = MouthPosition(x=0.5, y=0.62, width=0.16)
# Mouth position inside a detected face box (fractions of the box).
_MOUTH_IN_FACE = (0.5, 0.78, 0.40)

_FORMATS: dict[str, tuple[set[str], set[str]]] = {
    "JPEG": ({"jpg", "jpeg"}, {"image/jpeg", "image/jpg", "image/pjpeg"}),
    "PNG": ({"png"}, {"image/png"}),
    "WEBP": ({"webp"}, {"image/webp"}),
}
UNSUPPORTED = "Unsupported image format. Use JPG, PNG or WebP."


def sniff_format(data: bytes) -> str | None:
    if data[:3] == b"\xff\xd8\xff":
        return "JPEG"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "PNG"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "WEBP"
    return None


def max_avatar_bytes() -> int:
    return get_settings().max_avatar_size_mb * 1024 * 1024


def too_large_message() -> str:
    return f"The image is too large. Maximum size is {get_settings().max_avatar_size_mb} MB."


def _format_of_name(filename: str | None) -> str | None:
    extension = PurePath(filename or "").suffix.lower().lstrip(".")
    return next((fmt for fmt, (exts, _) in _FORMATS.items() if extension in exts), None)


def _format_of_mime(content_type: str | None) -> str | None:
    mime = (content_type or "").split(";", 1)[0].strip().lower()
    return next((fmt for fmt, (_, mimes) in _FORMATS.items() if mime in mimes), None)


def _decode(data: bytes, expected: str) -> Image.Image:
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        with Image.open(io.BytesIO(data)) as probe:
            if probe.format != expected:
                raise InvalidImageError("The file's content doesn't match its image type.", 415)
            probe.verify()
        image = Image.open(io.BytesIO(data))
        image.load()
    except InvalidImageError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise InvalidImageError("The image has too many pixels.", 413) from exc
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise InvalidImageError("The image couldn't be read. Please upload another file.") from exc
    return image


def normalise(image: Image.Image) -> Image.Image:
    image = ImageOps.exif_transpose(image)
    if image.mode in ("RGBA", "LA", "P"):
        image = image.convert("RGBA")
        background = Image.new("RGB", image.size, (255, 255, 255))
        background.paste(image, mask=image.getchannel("A"))
        image = background
    else:
        image = image.convert("RGB")
    if min(image.size) < MIN_SIDE:
        raise InvalidImageError(f"The image is too small. Use at least {MIN_SIDE}×{MIN_SIDE} pixels.")
    scale = min(1.0, MAX_SIDE / max(image.size))
    width = max(2, int(image.width * scale) // 2 * 2)
    height = max(2, int(image.height * scale) // 2 * 2)
    if (width, height) != image.size:
        image = image.resize((width, height), Image.Resampling.LANCZOS)
    return image


@lru_cache
def _face_detector():
    try:
        import cv2

        path = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
        detector = cv2.CascadeClassifier(str(path))
        return None if detector.empty() else detector
    except Exception as exc:  # noqa: BLE001 - detection is optional
        logger.warning("Face detector unavailable: %s", exc)
        return None


def find_mouth(image: Image.Image) -> tuple[MouthPosition, bool, int]:
    """(mouth position, whether a face was found, how many faces)."""
    detector = _face_detector()
    if detector is None:
        return DEFAULT_MOUTH, False, 0
    import cv2
    import numpy as np

    gray = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2GRAY)
    smallest = max(24, int(min(image.size) * 0.12))
    faces = detector.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=6, minSize=(smallest, smallest))
    if len(faces) == 0:
        return DEFAULT_MOUTH, False, 0
    x, y, w, h = max(faces, key=lambda f: f[2] * f[3])  # the largest face speaks
    mx, my, mw = _MOUTH_IN_FACE
    mouth = MouthPosition(
        x=round(float(x + mx * w) / image.width, 4),
        y=round(float(y + my * h) / image.height, 4),
        width=round(float(mw * w) / image.width, 4),
    )
    return mouth, True, len(faces)


def to_png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)  # a fresh file: no EXIF/GPS/metadata
    return buffer.getvalue()


def process_upload(data: bytes, filename: str | None, content_type: str | None) -> AvatarImage:
    """Validate an upload and return it normalised, with its mouth position. Raises InvalidImageError."""
    if not data:
        raise InvalidImageError("The image is empty.")
    if len(data) > max_avatar_bytes():
        raise InvalidImageError(too_large_message(), 413)
    by_name, by_mime, by_bytes = _format_of_name(filename), _format_of_mime(content_type), sniff_format(data)
    if by_name is None or by_mime is None:
        raise InvalidImageError(UNSUPPORTED, 415)
    if not (by_name == by_mime == by_bytes):
        raise InvalidImageError("The file's content doesn't match its image type.", 415)

    image = normalise(_decode(data, by_bytes))
    mouth, face_detected, faces = find_mouth(image)
    logger.info("Avatar image %dx%d processed: %d face(s) found", image.width, image.height, faces)
    return AvatarImage(
        png=to_png(image),
        width=image.width,
        height=image.height,
        mouth=mouth,
        face_detected=face_detected,
        faces_found=faces,
    )
