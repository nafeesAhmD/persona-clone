"""Builds the reference-knowledge block sent to the LLM with each question.

Retrieved chunks and long-term memories are untrusted content (anyone can put
"ignore your instructions" in a document or a memory). They are therefore:
- placed in the *user* turn inside <reference_knowledge>, never in the system prompt;
- stripped of anything that looks like our own delimiter tags, section headings
  or item markers, so they can't close the block early or fake a section;
- sorted by relevance, de-duplicated and capped (RAG_MAX_CONTEXT_CHARS for
  knowledge, MEMORY_MAX_CONTEXT_CHARS for memories).
The system prompt (clone_prompt.py) tells the model that this block is data.

With approved memories the block has two sections, memories first:
    ## LONG-TERM MEMORY
    [Memory 1] (communication_preference) The user prefers simple explanations.

    ## CLONE KNOWLEDGE
    [Knowledge Source 1] ...
Without memories it is only the knowledge sources, as before.
"""

import re
from dataclasses import dataclass, field, replace

from app.ai.memory_search import RetrievedMemory
from app.services.qdrant_service import MemoryHit

NO_KNOWLEDGE = "(No relevant knowledge was found for this question.)"
MEMORY_HEADING = "## LONG-TERM MEMORY"
KNOWLEDGE_HEADING = "## CLONE KNOWLEDGE"
# Any opening/closing tag of our own delimiters inside untrusted text.
_OUR_TAGS = re.compile(r"</?\s*(reference_knowledge|user_message)\b[^>]*>", re.IGNORECASE)
# Our section headings and item markers, if they appear inside untrusted text.
_OUR_HEADINGS = re.compile(r"#+[ \t]*(long[- ]term memory|clone knowledge)\b", re.IGNORECASE)
_OUR_MARKERS = re.compile(r"\[(\s*(?:knowledge source|memory)\s+\d+\s*)\]", re.IGNORECASE)
_SOURCE_OVERHEAD = 60  # "[Knowledge Source N]\nTitle: ...\nContent:\n" lines
_MEMORY_OVERHEAD = 50  # "[Memory N] (type) " prefix


@dataclass
class RagContext:
    text: str  # the block for the LLM (NO_KNOWLEDGE when empty)
    hits: list[MemoryHit] = field(default_factory=list)  # the chunks actually included
    memories: list[RetrievedMemory] = field(default_factory=list)  # approved memories included

    @property
    def has_knowledge(self) -> bool:
        return bool(self.hits)


def _neutralise(text: str) -> str:
    text = _OUR_TAGS.sub(lambda m: m.group(0).replace("<", "(").replace(">", ")"), text)
    text = _OUR_HEADINGS.sub(lambda m: m.group(0).replace("#", ""), text)
    return _OUR_MARKERS.sub(r"(\1)", text)


def select_hits(search_results: list[MemoryHit], max_chars: int) -> list[MemoryHit]:
    """Strongest first, no duplicate chunks/texts, total text within max_chars."""
    chosen: list[MemoryHit] = []
    seen_chunks: set[tuple[str, int]] = set()
    seen_texts: set[str] = set()
    used = 0
    for hit in sorted(search_results, key=lambda h: h.score, reverse=True):
        normalised = " ".join(hit.text.split()).lower()
        if (hit.document_id, hit.chunk_index) in seen_chunks or normalised in seen_texts:
            continue
        cost = len(hit.text) + len(hit.title) + _SOURCE_OVERHEAD
        if used + cost > max_chars:
            if not chosen:  # a single huge chunk: keep its beginning rather than nothing
                room = max(max_chars - len(hit.title) - _SOURCE_OVERHEAD, 0)
                chosen.append(replace(hit, text=hit.text[:room]))
            break
        chosen.append(hit)
        seen_chunks.add((hit.document_id, hit.chunk_index))
        seen_texts.add(normalised)
        used += cost
    return chosen


def select_memories(memories: list[RetrievedMemory], max_chars: int) -> list[RetrievedMemory]:
    """Most relevant first, no repeated texts, total within max_chars (whole memories only)."""
    chosen: list[RetrievedMemory] = []
    seen: set[str] = set()
    used = 0
    for memory in sorted(memories, key=lambda m: m.score, reverse=True):
        normalised = " ".join(memory.content.split()).lower()
        cost = len(memory.content) + _MEMORY_OVERHEAD
        if normalised in seen or used + cost > max_chars:
            continue
        chosen.append(memory)
        seen.add(normalised)
        used += cost
    return chosen


def build_rag_context(
    search_results: list[MemoryHit],
    max_chars: int = 12_000,
    memories: list[RetrievedMemory] | None = None,
    memory_max_chars: int = 5000,
) -> RagContext:
    hits = select_hits(search_results, max_chars)
    chosen_memories = select_memories(memories or [], memory_max_chars)
    blocks = [
        f"[Knowledge Source {number}]\nTitle: {_neutralise(hit.title)}\nContent:\n{_neutralise(hit.text.strip())}"
        for number, hit in enumerate(hits, 1)
    ]
    knowledge = "\n\n".join(blocks) if hits else NO_KNOWLEDGE
    if not chosen_memories:
        return RagContext(text=knowledge, hits=hits)

    memory_lines = [
        f"[Memory {number}] ({memory.memory_type}) {_neutralise(' '.join(memory.content.split()))}"
        for number, memory in enumerate(chosen_memories, 1)
    ]
    text = f"{MEMORY_HEADING}\n" + "\n".join(memory_lines) + f"\n\n{KNOWLEDGE_HEADING}\n{knowledge}"
    return RagContext(text=text, hits=hits, memories=chosen_memories)


def compose_user_turn(user_message: str, context: str | None) -> str:
    """The final user turn: reference knowledge (data) first, then the question."""
    if context is None:
        return user_message
    return (
        f"<reference_knowledge>\n{context}\n</reference_knowledge>\n\n"
        f"<user_message>\n{_neutralise(user_message)}\n</user_message>"
    )
