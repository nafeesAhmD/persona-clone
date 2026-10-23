"""The planner: asks the existing LLM provider for the next step as strict JSON.

One call per step via `factory.get_llm_provider().generate_json(system, user, schema)`.
The reply is parsed and validated into a PlannerDecision; an invalid reply gets ONE
re-ask, then the run fails safely. Only the decision's public `summary` is ever stored
or shown; the raw model output is never kept.
"""

import json
import re
from collections.abc import Callable
from typing import Any

from app.agent.exceptions import AgentError
from app.agent.prompts import PLANNER_SCHEMA, REPAIR_MESSAGE
from app.agent.safety import short
from app.agent.schemas import PlannerDecision
from app.ai import factory
from app.models.memory import MEMORY_TYPES

MAX_ATTEMPTS = 2  # the first ask + one re-ask on an invalid reply
_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


class PlannerOutputError(AgentError):
    """The planner's reply wasn't a valid decision."""


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def parse_decision(raw: str) -> PlannerDecision:
    """Strictly validate one planner reply."""
    if not isinstance(raw, str) or not raw.strip():
        raise PlannerOutputError("empty reply")
    try:
        data = json.loads(_FENCE.sub("", raw.strip()))
    except json.JSONDecodeError as exc:
        raise PlannerOutputError("not JSON") from exc
    if not isinstance(data, dict):
        raise PlannerOutputError("not an object")
    action = data.get("action")
    summary = short(_text(data.get("summary")), 200)
    if action == "tool":
        tool = _text(data.get("tool"))
        if not tool or len(tool) > 60:
            raise PlannerOutputError("missing tool")
        arguments = data.get("arguments")
        if arguments is None:
            raw_args = data.get("arguments_json")
            raw_args = raw_args.strip() if isinstance(raw_args, str) and raw_args.strip() else "{}"
            try:
                arguments = json.loads(raw_args)
            except json.JSONDecodeError as exc:
                raise PlannerOutputError("arguments not JSON") from exc
        if not isinstance(arguments, dict):
            raise PlannerOutputError("arguments not an object")
        return PlannerDecision(action="tool", summary=summary or f"Using {tool}", tool=tool, arguments=arguments)
    if action == "final":
        answer = _text(data.get("answer"))
        if not answer:
            raise PlannerOutputError("missing answer")
        return PlannerDecision(action="final", summary=summary or "Preparing the final answer", answer=answer)
    if action == "propose_memory":
        memory = data.get("memory") if isinstance(data.get("memory"), dict) else {}
        content = _text(memory.get("content") or data.get("memory_content"))
        memory_type = _text(memory.get("memory_type") or data.get("memory_type")) or "fact"
        if not content or len(content) > 1000:
            raise PlannerOutputError("missing memory")
        if memory_type not in MEMORY_TYPES:
            memory_type = "other"
        return PlannerDecision(
            action="propose_memory",
            summary=summary or "Suggesting something to remember",
            memory={"content": content, "memory_type": memory_type},
        )
    raise PlannerOutputError("unknown action")


def decide(system_prompt: str, user_message: str, run: Callable[[Any], Any]) -> PlannerDecision:
    """Ask for the next step; `run(coroutine)` runs the provider call (with the run's time limit)."""
    provider = factory.get_llm_provider()
    message = user_message
    last: PlannerOutputError | None = None
    for _ in range(MAX_ATTEMPTS):
        raw = run(provider.generate_json(system_prompt, message, PLANNER_SCHEMA))
        try:
            return parse_decision(raw)
        except PlannerOutputError as exc:
            last = exc
            message = f"{user_message}\n\n{REPAIR_MESSAGE}"
    raise PlannerOutputError("The agent couldn't plan the next step.") from last
