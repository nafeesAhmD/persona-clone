import re
import unicodedata
from collections.abc import Callable

MAX_SLUG_LENGTH = 60
FALLBACK_SLUG = "clone"


def slugify(value: str) -> str:
    """Turn a display name into a URL slug: 'Ayaan AI!' -> 'ayaan-ai'.

    Names with no Latin letters or digits fall back to 'clone'.
    """
    ascii_text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    slug = slug[:MAX_SLUG_LENGTH].rstrip("-")
    return slug or FALLBACK_SLUG


def unique_slug(name: str, is_taken: Callable[[str], bool]) -> str:
    """First free slug among "base", "base-2", "base-3", ..."""
    base = slugify(name)
    if not is_taken(base):
        return base
    counter = 2
    while True:
        suffix = f"-{counter}"
        candidate = f"{base[: MAX_SLUG_LENGTH - len(suffix)].rstrip('-')}{suffix}"
        if not is_taken(candidate):
            return candidate
        counter += 1
