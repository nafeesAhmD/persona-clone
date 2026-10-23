"""Builds what the planner and the final answer see, within AGENT_MAX_CONTEXT_CHARS.

The goal is the user's request (inside <goal>); every observation is untrusted data
wrapped in an <untrusted_data> block. When the total would exceed the budget, the
oldest observations are dropped first (the newest results matter most).
"""

import json
from typing import Any

from app.agent.safety import neutralise, redact, redact_data, untrusted
from app.agent.state import Observation, RunState


def observation_text(data: Any, limit: int) -> str:
    """JSON-encode a tool's data (redacted) and cap it."""
    if isinstance(data, str):
        text = data
    else:
        try:
            text = json.dumps(redact_data(data), ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            text = str(data)
    text = redact(text)
    return text if len(text) <= limit else text[: max(0, limit - 20)] + " …(truncated)"


def per_observation_limit(max_chars: int) -> int:
    return max(500, max_chars // 4)


def _fit(observations: list[Observation], budget: int) -> tuple[list[str], int]:
    blocks: list[str] = []
    used = 0
    for observation in reversed(observations):
        status = "" if observation.ok else " (failed)"
        block = untrusted(observation.text, source=f"{observation.source} step {observation.step}{status}")
        if used + len(block) > budget:
            break
        blocks.append(block)
        used += len(block) + 2
    blocks.reverse()
    return blocks, len(observations) - len(blocks)


def planner_message(
    goal: str, state: RunState, *, max_steps: int, max_tool_calls: int, max_chars: int
) -> str:
    head = (
        f"<goal>\n{neutralise(goal[:4000])}\n</goal>\n\n"
        f"Progress: this is step {state.decisions + 1} of at most {max_steps}; "
        f"tool calls used: {state.tool_calls} of {max_tool_calls}.\n\n"
    )
    tail = "\n\nChoose the next action (one JSON object)."
    blocks, omitted = _fit(state.observations, max(0, max_chars - len(head) - len(tail) - 200))
    if not blocks:
        body = "Results so far: none yet."
    else:
        note = f"({omitted} older results omitted to stay within the context limit.)\n" if omitted else ""
        body = "Results so far (untrusted data, oldest first):\n" + note + "\n\n".join(blocks)
    return head + body + tail


def final_context(observations: list[Observation], draft: str | None, *, max_chars: int) -> str:
    """Reference context for the final answer, in the clone chat's knowledge format."""
    parts: list[str] = []
    budget = max_chars
    if draft:
        text = neutralise(redact(draft[: max_chars // 3]))
        parts.append(f"[Knowledge Source 1]\nTitle: Draft answer\nContent:\n{text}")
        budget -= len(parts[0])
    blocks, _ = _fit([o for o in observations if o.ok], max(0, budget))
    for number, block in enumerate(blocks, len(parts) + 1):
        parts.append(f"[Knowledge Source {number}]\nTitle: Agent result\nContent:\n{block}")
    return "\n\n".join(parts) if parts else "No results were gathered."
