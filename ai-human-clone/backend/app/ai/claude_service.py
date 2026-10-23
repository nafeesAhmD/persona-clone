import logging
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager

import anthropic

from app.ai.base import (
    ChatTurn,
    GenerationOptions,
    LLMError,
    LLMNotConfiguredError,
    LLMProvider,
    LLMRateLimitError,
    LLMRefusalError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from app.ai.rag_context import compose_user_turn
from app.core.config import Settings

logger = logging.getLogger(__name__)

# Server-side refusal fallback: if Claude's safety classifiers decline a request,
# the API re-runs it on Anthropic's recommended fallback model in the same call.
_FALLBACK_BETA = "server-side-fallback-2026-07-01"


class ClaudeService(LLMProvider):
    name = "claude"

    def __init__(self, settings: Settings) -> None:
        self.model = settings.claude_model
        self.max_tokens = settings.claude_max_tokens
        self.effort = settings.claude_effort
        self._client = (
            anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key, timeout=settings.llm_timeout_seconds)
            if settings.anthropic_api_key
            else None
        )

    @property
    def client(self) -> anthropic.AsyncAnthropic:
        if self._client is None:
            raise LLMNotConfiguredError("ANTHROPIC_API_KEY is not set")
        return self._client

    def _request(
        self,
        system_prompt: str,
        user_message: str,
        context: str | None,
        history: list[ChatTurn] | None,
        options: GenerationOptions | None = None,
    ) -> dict:
        messages = [{"role": turn["role"], "content": turn["content"]} for turn in history or []]
        messages.append({"role": "user", "content": compose_user_turn(user_message, context)})
        max_tokens = min(self.max_tokens, options.max_tokens) if options and options.max_tokens else self.max_tokens
        return {
            "model": (options.model_for(self.name) if options else None) or self.model,
            "max_tokens": max_tokens,
            "system": system_prompt,
            "messages": messages,
            "output_config": {"effort": self.effort},
            "betas": [_FALLBACK_BETA],
            "fallbacks": "default",
        }

    @contextmanager
    def _translate_errors(self) -> Iterator[None]:
        # Technical detail goes in the exception text (logged); users see each
        # class's user_message. Order matters: subclasses before their parents.
        try:
            yield
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as exc:
            raise LLMNotConfiguredError(f"Anthropic rejected the credentials ({exc.status_code})") from exc
        except anthropic.RateLimitError as exc:
            raise LLMRateLimitError("Claude rate limit reached") from exc
        except anthropic.InternalServerError as exc:
            raise LLMUnavailableError(f"Claude server error ({exc.status_code})") from exc
        except anthropic.APIStatusError as exc:
            raise LLMError(f"Claude API error {exc.status_code}: {exc.message}") from exc
        except anthropic.APITimeoutError as exc:
            raise LLMTimeoutError("Claude request timed out") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMUnavailableError("Could not reach the Claude API") from exc

    def _check_stop_reason(self, stop_reason: str | None) -> None:
        if stop_reason == "refusal":
            raise LLMRefusalError("The model declined to answer this request")
        if stop_reason == "max_tokens":
            logger.warning("Claude response truncated at max_tokens=%s", self.max_tokens)

    async def generate_response(
        self,
        system_prompt: str,
        user_message: str,
        context: str | None = None,
        history: list[ChatTurn] | None = None,
        options: GenerationOptions | None = None,
    ) -> str:
        with self._translate_errors():
            response = await self.client.beta.messages.create(
                **self._request(system_prompt, user_message, context, history, options)
            )
        self._check_stop_reason(response.stop_reason)
        return "".join(block.text for block in response.content if block.type == "text")

    async def generate_json(self, system_prompt: str, user_message: str, schema: dict) -> str:
        """Structured output: Claude's reply is constrained to `schema`."""
        request = self._request(system_prompt, user_message, None, None)
        request["output_config"] = {**request["output_config"], "format": {"type": "json_schema", "schema": schema}}
        with self._translate_errors():
            response = await self.client.beta.messages.create(**request)
        self._check_stop_reason(response.stop_reason)
        return "".join(block.text for block in response.content if block.type == "text")

    async def stream_response(
        self,
        system_prompt: str,
        user_message: str,
        context: str | None = None,
        history: list[ChatTurn] | None = None,
        options: GenerationOptions | None = None,
    ) -> AsyncIterator[str]:
        with self._translate_errors():
            async with self.client.beta.messages.stream(
                **self._request(system_prompt, user_message, context, history, options)
            ) as stream:
                async for text in stream.text_stream:
                    yield text
                final = await stream.get_final_message()
        self._check_stop_reason(final.stop_reason)

    async def check_connection(self) -> dict[str, object]:
        """Look up the configured model; validates the key without spending tokens."""
        if self._client is None:
            return {"provider": self.name, "configured": False, "reachable": False, "model": self.model}
        try:
            model = await self._client.models.retrieve(self.model)
            return {"provider": self.name, "configured": True, "reachable": True, "model": model.id}
        except anthropic.AuthenticationError:
            return {
                "provider": self.name,
                "configured": True,
                "reachable": False,
                "model": self.model,
                "error": "invalid API key",
            }
        except (anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
            logger.warning("Claude connection check failed: %s", exc)
            return {
                "provider": self.name,
                "configured": True,
                "reachable": False,
                "model": self.model,
                "error": type(exc).__name__,
            }
