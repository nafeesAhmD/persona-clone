import asyncio
import re
from collections.abc import AsyncIterator

from app.ai.base import ChatTurn, GenerationOptions, LLMProvider, LLMUnsupportedError
from app.core.config import Settings

# Matches the blocks produced by app/ai/rag_context.build_rag_context.
_EXCERPT = re.compile(
    r"\[Knowledge Source \d+\]\nTitle: (?P<source>[^\n]*)\nContent:\n(?P<text>.*?)(?=\n\n\[Knowledge Source \d+\]|\Z)",
    re.DOTALL,
)

_MAX_EXCERPTS = 2
_MAX_CHARS = 400


class DemoService(LLMProvider):
    """Free fallback used when no LLM API key is configured.

    It doesn't generate language: it replies with the most relevant passages
    retrieved from the owner's documents, so the full pipeline can still be
    demonstrated without a paid model.
    """

    name = "demo"

    def __init__(self, settings: Settings | None = None) -> None:
        pass

    async def generate_response(
        self,
        system_prompt: str,
        user_message: str,
        context: str | None = None,
        history: list[ChatTurn] | None = None,
        options: GenerationOptions | None = None,
    ) -> str:
        excerpts = list(_EXCERPT.finditer(context or ""))[:_MAX_EXCERPTS]
        if not excerpts:
            return (
                "I couldn't find anything about that in my owner's documents.\n\n"
                "(Demo mode: no AI model is connected, so I can only show matching passages.)"
            )

        parts = ["Here's what I found in my owner's documents:"]
        for match in excerpts:
            text = " ".join(match["text"].split())
            if len(text) > _MAX_CHARS:
                text = text[:_MAX_CHARS].rsplit(" ", 1)[0] + "…"
            parts.append(f"• {text}\n  (from {match['source']})")
        parts.append("(Demo mode: these are passages, not an AI-written answer. Add an API key for full replies.)")
        return "\n\n".join(parts)

    async def stream_response(
        self,
        system_prompt: str,
        user_message: str,
        context: str | None = None,
        history: list[ChatTurn] | None = None,
        options: GenerationOptions | None = None,
    ) -> AsyncIterator[str]:
        # Reveal the reply word by word so the UI behaves like a real model.
        text = await self.generate_response(system_prompt, user_message, context, history)
        for word in re.split(r"(\s+)", text):
            if word:
                yield word
                await asyncio.sleep(0.01)

    async def generate_json(self, system_prompt: str, user_message: str, schema: dict) -> str:
        # Tasks such as memory extraction need a real model; don't fake their results.
        raise LLMUnsupportedError("Demo mode can't produce structured output")

    async def check_connection(self) -> dict[str, object]:
        return {
            "provider": self.name,
            "configured": True,
            "reachable": True,
            "model": "none",
            "error": "demo mode: set GEMINI_API_KEY or ANTHROPIC_API_KEY for AI answers",
        }
