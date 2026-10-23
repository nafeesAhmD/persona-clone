"""Split document text into overlapping chunks for embedding.

Text is packed into chunks sentence by sentence, keeping paragraph breaks.
A sentence longer than the chunk size is split at word boundaries, so words are
never cut (except a single "word" longer than a chunk, such as a huge URL).
Each chunk after the first begins with the last ~`overlap` characters (whole
words) of the previous one, so a fact on a boundary is complete in one chunk.
"""

import re
from dataclasses import dataclass

_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")
# Latin and Urdu sentence endings.
_SENTENCE_END = re.compile(r"(?<=[.!?۔؟])\s+")


@dataclass(frozen=True)
class ChunkingConfig:
    chunk_size: int = 1000
    overlap: int = 150

    def __post_init__(self) -> None:
        if self.chunk_size < 50:
            raise ValueError("chunk_size must be at least 50 characters")
        if not 0 <= self.overlap < self.chunk_size // 2:
            raise ValueError("overlap must be between 0 and half the chunk size")


@dataclass(frozen=True)
class _Unit:
    text: str
    starts_paragraph: bool


def _split_words(sentence: str, limit: int) -> list[str]:
    pieces: list[str] = []
    current = ""
    for word in sentence.split():
        if len(word) > limit:
            if current:
                pieces.append(current)
                current = ""
            pieces.extend(word[i : i + limit] for i in range(0, len(word), limit))
        elif not current:
            current = word
        elif len(current) + 1 + len(word) <= limit:
            current = f"{current} {word}"
        else:
            pieces.append(current)
            current = word
    if current:
        pieces.append(current)
    return pieces


def _units(text: str, limit: int) -> list[_Unit]:
    units: list[_Unit] = []
    for paragraph in _PARAGRAPH_BREAK.split(text):
        paragraph = " ".join(paragraph.split())
        first = True
        for sentence in _SENTENCE_END.split(paragraph):
            if not sentence:
                continue
            for piece in [sentence] if len(sentence) <= limit else _split_words(sentence, limit):
                units.append(_Unit(piece, starts_paragraph=first))
                first = False
    return units


def _tail(text: str, overlap: int) -> str:
    """The last whole words of `text`, at most `overlap` characters."""
    if overlap == 0:
        return ""
    tail = text[-overlap:]
    if len(text) <= overlap:
        return tail
    space = tail.find(" ")
    return tail[space + 1 :] if space != -1 else ""


def chunk_text(text: str, config: ChunkingConfig) -> list[str]:
    chunks: list[str] = []
    current = ""
    for unit in _units(text.strip(), config.chunk_size):
        separator = ("\n\n" if unit.starts_paragraph else " ") if current else ""
        if len(current) + len(separator) + len(unit.text) <= config.chunk_size:
            current = f"{current}{separator}{unit.text}"
            continue
        chunks.append(current)
        overlap = _tail(current, config.overlap)
        # Carry the overlap only if the new unit still fits after it.
        fits = overlap and len(overlap) + 1 + len(unit.text) <= config.chunk_size
        current = f"{overlap} {unit.text}" if fits else unit.text
    if current:
        chunks.append(current)
    return chunks
