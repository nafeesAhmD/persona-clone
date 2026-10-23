"""Small helpers shared by the built-in tools: strict argument checks and text caps.

Arguments come from the planner (an LLM), so they are untrusted: every tool checks
types, lengths and unknown keys (additionalProperties: false) before running.
"""

from typing import Any

from app.agent.exceptions import ToolInputError
from app.agent.schemas import ToolContext


def check_object(arguments: Any, allowed: set[str], required: set[str] | None = None) -> dict[str, Any]:
    if not isinstance(arguments, dict):
        raise ToolInputError("Arguments must be a JSON object.")
    unexpected = sorted(str(key)[:40] for key in arguments if key not in allowed)
    if unexpected:
        raise ToolInputError(f"Unexpected argument(s): {', '.join(unexpected[:5])}.")
    missing = sorted((required or set()) - set(arguments))
    if missing:
        raise ToolInputError(f"Missing required argument(s): {', '.join(missing)}.")
    return arguments


def string_arg(
    arguments: dict[str, Any],
    key: str,
    *,
    max_length: int,
    required: bool = True,
) -> str | None:
    """A non-empty string (stripped) of at most max_length characters; None if optional and absent."""
    if key not in arguments or arguments[key] is None:
        if required:
            raise ToolInputError(f"'{key}' is required.")
        return None
    value = arguments[key]
    if not isinstance(value, str):
        raise ToolInputError(f"'{key}' must be a string.")
    value = value.strip()
    if not value:
        raise ToolInputError(f"'{key}' must not be empty.")
    if len(value) > max_length:
        raise ToolInputError(f"'{key}' must be at most {max_length} characters.")
    return value


def int_arg(arguments: dict[str, Any], key: str, *, minimum: int, maximum: int, default: int) -> int:
    if key not in arguments or arguments[key] is None:
        return default
    value = arguments[key]
    # bool is a subclass of int; a whole float (5.0) from a JSON encoder is accepted.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ToolInputError(f"'{key}' must be an integer.")
    if isinstance(value, float):
        if not value.is_integer():
            raise ToolInputError(f"'{key}' must be an integer.")
        value = int(value)
    if not minimum <= value <= maximum:
        raise ToolInputError(f"'{key}' must be between {minimum} and {maximum}.")
    return value


def truncate(text: str | None, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(limit - 1, 0)].rstrip() + "…"


def is_public_run(ctx: ToolContext) -> bool:
    """Visitor runs and non-owner runs may only see content the owner marked public."""
    return ctx.source == "public" or not ctx.is_owner
