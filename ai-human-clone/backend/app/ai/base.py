import json
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal, TypedDict


class LLMError(Exception):
    """Base error for any LLM provider failure the API layer should handle.

    `str(exc)` holds technical detail for server logs; `user_message` is the
    safe text shown to users (no keys, hosts, or raw provider errors).
    """

    status_code = 502
    user_message = "The AI service had a problem answering. Please try again."


class LLMNotConfiguredError(LLMError):
    """Missing or rejected credentials / configuration."""

    status_code = 503
    user_message = "The AI service is not available right now."


class LLMRateLimitError(LLMError):
    """The provider's rate limit or quota was hit."""

    status_code = 429
    user_message = "The AI service is busy right now. Please try again in a moment."


class LLMTimeoutError(LLMError):
    """The provider didn't answer in time."""

    status_code = 504
    user_message = "The AI took too long to respond. Please try again."


class LLMUnavailableError(LLMError):
    """The provider is unreachable or overloaded."""

    status_code = 503
    user_message = "The AI service is temporarily unavailable. Please try again shortly."


class LLMRefusalError(LLMError):
    """The model declined to answer the request."""

    status_code = 422
    user_message = "The AI declined to answer this request."


class LLMUnsupportedError(LLMError):
    """The configured provider can't do this task (demo mode has no language model)."""

    status_code = 503
    user_message = "This needs a connected AI model, but the app is running in demo mode."


@dataclass(frozen=True)
class GenerationOptions:
    """Per-request overrides, e.g. a cheaper model and shorter answers for public visitors.

    `model` applies only to the provider named in `model_provider`; None keeps the
    configured model. `max_tokens` can only lower the configured limit.
    """

    max_tokens: int | None = None
    model: str | None = None
    model_provider: str | None = None

    def model_for(self, provider: str) -> str | None:
        return self.model if self.model and self.model_provider == provider else None


class ChatTurn(TypedDict):
    role: Literal["user", "assistant"]
    content: str


class LLMProvider(ABC):
    """Interface every LLM backend implements, so providers can be swapped via config."""

    name: str

    @property
    def model_name(self) -> str:
        """The model this provider is configured to use (stored with each answer)."""
        return getattr(self, "model", self.name)

    @abstractmethod
    async def generate_response(
        self,
        system_prompt: str,
        user_message: str,
        context: str | None = None,
        history: list[ChatTurn] | None = None,
        options: GenerationOptions | None = None,
    ) -> str:
        """Return the model's text answer.

        `context` is the reference-knowledge block (see app/ai/rag_context.py);
        it is placed in the user turn, marked as data, never in the system prompt.
        `history` holds earlier turns of the conversation, oldest first.
        """

    async def stream_response(
        self,
        system_prompt: str,
        user_message: str,
        context: str | None = None,
        history: list[ChatTurn] | None = None,
        options: GenerationOptions | None = None,
    ) -> AsyncIterator[str]:
        """Yield the answer in pieces as it is generated.

        Providers without streaming inherit this, which yields the whole answer at once.
        """
        yield await self.generate_response(system_prompt, user_message, context, history, options)

    async def generate_json(self, system_prompt: str, user_message: str, schema: dict) -> str:
        """Return a JSON document (as text) that should match `schema`.

        `user_message` is sent as-is (no reference-knowledge wrapping). This
        default asks for JSON in the prompt; providers with native structured
        output override it. Callers must still validate the result.
        """
        instructions = f"{system_prompt}\n\nRespond with JSON only, matching this JSON schema:\n{json.dumps(schema)}"
        return await self.generate_response(instructions, user_message)

    @abstractmethod
    async def check_connection(self) -> dict[str, object]:
        """Verify credentials/reachability without generating any tokens."""
