"""Run state of one agent execution: counters, observations and loop-detection data.

The durable state lives in PostgreSQL (the execution row and its steps), so a run that
pauses for a confirmation can be resumed by another worker. Observations (the tool
outputs the planner reads) are NOT stored in step logs, which keep only short safe
summaries; they're kept in a small in-process cache while the run is alive. If the
cache was lost (e.g. a restart while waiting for confirmation), the planner continues
from the steps' safe summaries.
"""

import hashlib
import json
import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from app.models.agent import AgentExecution, AgentStep

# Loop detection: the same tool with the same (normalised) arguments may be requested at
# most this many times; this many consecutive empty/failed results also stop the run.
MAX_SAME_CALL = 2
MAX_NO_PROGRESS = 3
NO_PROGRESS = "Agent stopped because it could not make further progress."


@dataclass
class Observation:
    step: int
    source: str  # e.g. "tool:knowledge_search", "user", "system"
    text: str  # already redacted and size-capped
    ok: bool = True


@dataclass
class RunState:
    execution_id: uuid.UUID | None = None
    decisions: int = 0  # planner decisions used (the step limit counts these)
    tool_calls: int = 0
    elapsed_before: float = 0.0  # active seconds spent before a confirmation pause
    signatures: dict[str, int] = field(default_factory=dict)
    rejected: set[str] = field(default_factory=set)
    no_progress: int = 0
    observations: list[Observation] = field(default_factory=list)

    def count_request(self, signature: str) -> int:
        self.signatures[signature] = self.signatures.get(signature, 0) + 1
        return self.signatures[signature]

    def record_result(self, ok: bool, empty: bool) -> None:
        self.no_progress = self.no_progress + 1 if (not ok or empty) else 0

    def observe(self, observation: Observation) -> None:
        self.observations.append(observation)
        _cache_put(self)


def _normalise(value: Any) -> Any:
    if isinstance(value, str):
        return " ".join(value.lower().split())
    if isinstance(value, dict):
        return {str(k): _normalise(v) for k, v in sorted(value.items())}
    if isinstance(value, list | tuple):
        return [_normalise(v) for v in value]
    return value


def signature(tool: str, arguments: dict[str, Any]) -> str:
    """A short hash of the tool + normalised arguments (safe to store)."""
    text = json.dumps([tool, _normalise(arguments)], sort_keys=True, default=str)
    return hashlib.sha256(text.encode()).hexdigest()[:24]


# --- In-process observation cache -----------------------------------------------------

_CACHE_SIZE = 200
_cache: "OrderedDict[uuid.UUID, list[Observation]]" = OrderedDict()
_cache_lock = threading.Lock()


def _cache_put(state: RunState) -> None:
    execution_id = state.execution_id
    if execution_id is None:
        return
    with _cache_lock:
        _cache[execution_id] = list(state.observations)
        _cache.move_to_end(execution_id)
        while len(_cache) > _CACHE_SIZE:
            _cache.popitem(last=False)


def forget(execution_id: uuid.UUID) -> None:
    with _cache_lock:
        _cache.pop(execution_id, None)


def load(execution: AgentExecution, steps: list[AgentStep]) -> RunState:
    """Rebuild the counters from the execution row and its steps."""
    state = RunState(
        execution_id=execution.id, decisions=execution.current_step or 0, tool_calls=execution.tool_calls or 0
    )
    pending = execution.pending_action or {}
    state.elapsed_before = float(pending.get("_elapsed", 0.0) or 0.0)
    for step in sorted(steps, key=lambda s: s.step_number):
        meta = step.input_metadata or {}
        out = step.output_metadata or {}
        if meta.get("signature"):
            state.count_request(meta["signature"])
        if step.step_type == "confirmation" and step.status == "rejected" and meta.get("action_signature"):
            state.rejected.add(meta["action_signature"])
            state.count_request(meta["action_signature"])
        if step.step_type == "tool" and step.status in ("succeeded", "failed"):
            state.record_result(step.status == "succeeded", bool(out.get("empty")))
    with _cache_lock:
        cached = _cache.get(execution.id)
    if cached is not None:
        state.observations = list(cached)
    else:
        for step in steps:
            summary = (step.output_metadata or {}).get("summary")
            if step.step_type in ("tool", "confirmation", "memory_proposal") and summary:
                source = f"tool:{step.tool_name}" if step.tool_name else "system"
                state.observations.append(
                    Observation(step.step_number, source, f"(summary of an earlier step) {summary}", step.status != "failed")
                )
    return state
