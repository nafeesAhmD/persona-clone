"""Runs one tool call with a timeout and limited retries.

- Each attempt runs in a small thread pool and is abandoned after
  min(tool.timeout_seconds, the run's remaining time). Tools must be short and
  read-only; an abandoned attempt's result is ignored.
- Each attempt gets its own database session: a timed-out attempt keeps running in
  its thread (it cannot be stopped), so it must never share the run's session.
- Only LOW risk tools are retried automatically (up to AGENT_MAX_TOOL_RETRIES times,
  never after a timeout). Medium+ risk tools run at most once per approved call.
- Errors become safe messages: no stack traces, no secrets.
"""

import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, replace
from functools import lru_cache
from typing import Any

from sqlalchemy.orm import Session

from app.agent import runner
from app.agent.exceptions import AgentError
from app.agent.safety import short
from app.agent.schemas import RiskLevel, ToolContext, ToolResult
from app.agent.tool_registry import Tool

logger = logging.getLogger(__name__)

TOOL_TIMEOUT = "The tool took too long and was stopped."
TOOL_FAILED = "The tool failed."


@dataclass
class ToolOutcome:
    result: ToolResult
    attempts: int
    duration_ms: int
    timed_out: bool = False


@lru_cache
def _pool() -> ThreadPoolExecutor:
    return ThreadPoolExecutor(max_workers=4, thread_name_prefix="agent-tool")


def max_attempts(tool: Tool, retries: int) -> int:
    return 1 + max(0, retries) if tool.risk == RiskLevel.LOW else 1


def _run_isolated(tool: Tool, ctx: ToolContext, arguments: dict[str, Any]) -> ToolResult:
    with runner.SessionLocal() as db:
        try:
            return tool.run(replace(ctx, db=db), arguments)
        except Exception:
            _rollback(db)
            raise


def _attempt(tool: Tool, ctx: ToolContext, arguments: dict[str, Any], timeout: float) -> tuple[ToolResult, bool]:
    future = _pool().submit(_run_isolated, tool, ctx, dict(arguments))
    try:
        result = future.result(timeout=max(0.01, timeout))
    except FutureTimeout:
        future.cancel()
        return ToolResult(ok=False, error=TOOL_TIMEOUT), True
    except AgentError as exc:
        return ToolResult(ok=False, error=short(str(exc), 200) or TOOL_FAILED), False
    except Exception as exc:  # noqa: BLE001 - a tool must never crash the run
        logger.warning("Agent tool %s failed: %s", tool.name, type(exc).__name__)
        return ToolResult(ok=False, error=TOOL_FAILED), False
    if not isinstance(result, ToolResult):
        return ToolResult(ok=False, error="The tool returned an invalid result."), False
    return result, False


def _rollback(db: Session) -> None:
    try:
        db.rollback()
    except Exception:  # noqa: BLE001
        pass


def run_tool(
    tool: Tool,
    ctx: ToolContext,
    arguments: dict[str, Any],
    *,
    remaining: Callable[[], float],
    retries: int,
    on_attempt: Callable[[int, ToolResult, int], None] | None = None,
) -> ToolOutcome:
    """Run `tool` (with retries for low-risk tools); `remaining()` is the run's time left."""
    allowed = max_attempts(tool, retries)
    started = time.monotonic()
    attempt = 0
    result = ToolResult(ok=False, error=TOOL_TIMEOUT)
    timed_out = False
    while attempt < allowed:
        left = remaining()
        if left <= 0:
            timed_out = True
            break
        attempt += 1
        attempt_start = time.monotonic()
        result, timed_out = _attempt(tool, ctx, arguments, min(float(tool.timeout_seconds), left))
        if on_attempt is not None:
            on_attempt(attempt, result, int((time.monotonic() - attempt_start) * 1000))
        if result.ok or timed_out:
            break
    return ToolOutcome(result, attempt, int((time.monotonic() - started) * 1000), timed_out)
