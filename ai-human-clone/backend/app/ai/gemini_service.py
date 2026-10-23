import asyncio
import logging
from collections.abc import AsyncIterator

import httpx
from google import genai
from google.genai import errors, types

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

# Delays (seconds) before retrying a busy model; the last attempt uses the fallback model.
_RETRY_DELAYS = (1.0, 2.0)


class GeminiService(LLMProvider):
    name = "gemini"

    def __init__(self, settings: Settings) -> None:
        self.model = settings.gemini_model
        self.fallback_model = settings.gemini_fallback_model
        self.max_tokens = settings.gemini_max_tokens
        self.thinking_level = settings.gemini_thinking_level.upper()
        self._client = (
            genai.Client(
                api_key=settings.gemini_api_key,
                http_options=types.HttpOptions(timeout=int(settings.llm_timeout_seconds * 1000)),  # milliseconds
            )
            if settings.gemini_api_key
            else None
        )

    @property
    def client(self) -> genai.Client:
        if self._client is None:
            raise LLMNotConfiguredError("GEMINI_API_KEY is not set")
        return self._client

    @staticmethod
    def _is_auth_error(exc: errors.APIError) -> bool:
        # Google returns 400 (not 401) for a malformed or unknown key.
        return exc.code in (401, 403) or (exc.code == 400 and "API key" in (exc.message or ""))

    def _contents(self, user_message: str, context: str | None, history: list[ChatTurn] | None) -> list[types.Content]:
        # Gemini calls the assistant role "model".
        contents = [
            types.Content(
                role="model" if turn["role"] == "assistant" else "user",
                parts=[types.Part(text=turn["content"])],
            )
            for turn in history or []
        ]
        contents.append(
            types.Content(role="user", parts=[types.Part(text=compose_user_turn(user_message, context))])
        )
        return contents

    async def generate_response(
        self,
        system_prompt: str,
        user_message: str,
        context: str | None = None,
        history: list[ChatTurn] | None = None,
        options: GenerationOptions | None = None,
    ) -> str:
        return "".join(
            [piece async for piece in self.stream_response(system_prompt, user_message, context, history, options)]
        )

    async def stream_response(
        self,
        system_prompt: str,
        user_message: str,
        context: str | None = None,
        history: list[ChatTurn] | None = None,
        options: GenerationOptions | None = None,
    ) -> AsyncIterator[str]:
        extra = {}
        if options and options.max_tokens:
            extra["max_output_tokens"] = min(self.max_tokens, options.max_tokens)
        config = self._config(system_prompt, **extra)
        async for piece in self._stream(self._contents(user_message, context, history), config, options):
            yield piece

    async def generate_json(self, system_prompt: str, user_message: str, schema: dict) -> str:
        """Structured output: Gemini's reply is constrained to `schema`."""
        contents = [types.Content(role="user", parts=[types.Part(text=user_message)])]
        config = self._config(system_prompt, response_mime_type="application/json", response_json_schema=schema)
        return "".join([piece async for piece in self._stream(contents, config)])

    def _config(self, system_prompt: str, **extra: object) -> types.GenerateContentConfig:
        extra.setdefault("max_output_tokens", self.max_tokens)
        return types.GenerateContentConfig(
            system_instruction=system_prompt,
            # Less thinking = faster first word; chat answers rarely need deep reasoning.
            thinking_config=types.ThinkingConfig(thinking_level=self.thinking_level),
            # No tools are passed, so skip the SDK's automatic function-calling loop.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            **extra,
        )

    async def _stream(
        self, contents: list[types.Content], config: types.GenerateContentConfig, options: GenerationOptions | None = None
    ) -> AsyncIterator[str]:
        """One generation with retries on overload; the last attempt uses the fallback model.

        Free-tier quotas are per model, so a 429 on the main model goes straight
        to the fallback model instead of failing.
        """
        models = [(options.model_for(self.name) if options else None) or self.model] * (len(_RETRY_DELAYS) + 1)
        if self.fallback_model:
            models[-1] = self.fallback_model

        produced = False
        attempt = 0
        while attempt < len(models):
            model = models[attempt]
            attempt += 1
            try:
                stream = await self.client.aio.models.generate_content_stream(
                    model=model, contents=contents, config=config
                )
                async for chunk in stream:
                    if chunk.text:
                        produced = True
                        yield chunk.text
                break
            except errors.ServerError as exc:
                # 5xx usually means the model is temporarily overloaded. Only retry
                # before any text was sent, otherwise the reply would repeat.
                if produced or attempt == len(models):
                    logger.error("Gemini API error %s: %s", exc.code, exc.message)
                    raise LLMUnavailableError(f"Gemini server error {exc.code} after retries") from exc
                logger.warning("Gemini %s returned %s, retrying", model, exc.code)
                await asyncio.sleep(_RETRY_DELAYS[attempt - 1])
            except errors.ClientError as exc:
                if self._is_auth_error(exc):
                    raise LLMNotConfiguredError(f"Google rejected the Gemini API key ({exc.code})") from exc
                if exc.code == 429:
                    if not produced and model != models[-1] and self.fallback_model:
                        logger.warning("Gemini %s quota or rate limit reached, using %s", model, self.fallback_model)
                        attempt = len(models) - 1  # jump to the fallback model
                        continue
                    raise LLMRateLimitError("Gemini rate limit or free-tier quota reached") from exc
                raise LLMError(f"Gemini API error {exc.code}: {exc.message}") from exc
            except errors.APIError as exc:
                raise LLMError(f"Gemini API error {exc.code}: {exc.message}") from exc
            except httpx.TimeoutException as exc:
                raise LLMTimeoutError("Gemini request timed out") from exc
            except httpx.HTTPError as exc:
                raise LLMUnavailableError("Could not reach the Gemini API") from exc

        if not produced:
            # No text at all means the prompt or reply was blocked by safety filters.
            raise LLMRefusalError("The model declined to answer this request")

    async def check_connection(self) -> dict[str, object]:
        """Look up the configured model; validates the key without generating text."""
        status: dict[str, object] = {"provider": self.name, "configured": self._client is not None, "model": self.model}
        if self._client is None:
            return {**status, "reachable": False}
        try:
            model = await self._client.aio.models.get(model=self.model)
            return {**status, "reachable": True, "model": (model.name or self.model).removeprefix("models/")}
        except errors.APIError as exc:
            error = "invalid API key" if self._is_auth_error(exc) else f"API error {exc.code}"
            return {**status, "reachable": False, "error": error}
        except httpx.HTTPError as exc:
            logger.warning("Gemini connection check failed: %s", exc)
            return {**status, "reachable": False, "error": type(exc).__name__}
