"""Shared types for the agent: risk levels, tool context and results, planner decisions.

These are the contracts between the engine (agent.py/planner.py/executor.py), the
tools (tools/*) and the API (app/api/routes/agent.py). Keep them stable.
"""

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

from sqlalchemy.orm import Session


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        return ["low", "medium", "high", "critical"].index(self.value)


Source = Literal["app", "api", "public"]


@dataclass
class ToolContext:
    """What a tool may see. Tools get the clone and the account the run acts for, never
    raw settings, keys or other users' data."""

    db: Session
    clone: Any  # CloneProfile
    acting_user: Any  # User the run acts for (the clone owner for API/org runs)
    execution_id: uuid.UUID
    source: Source = "app"
    # True when the requester is the clone owner (owner-only data such as private
    # knowledge/approved memories). Public runs are never owner runs.
    is_owner: bool = True
    conversation_id: uuid.UUID | None = None


@dataclass
class ToolResult:
    """A tool's answer. `data` goes to the planner as untrusted data (JSON-safe, size
    capped by the engine); `summary` is a short, safe line for the visible step list."""

    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    summary: str = ""
    error: str | None = None  # safe message, never a stack trace or secret
    # True if this result added nothing new (used by loop detection).
    empty: bool = False


@dataclass
class PlannerDecision:
    """One planner step. action: "tool" (call `tool` with `arguments`), "final" (answer
    with `answer`), or "propose_memory" (suggest saving `memory` — never auto-saved).
    `summary` is the public one-line description shown in the UI (no hidden reasoning)."""

    action: Literal["tool", "final", "propose_memory"]
    summary: str = ""
    tool: str | None = None
    arguments: dict[str, Any] = field(default_factory=dict)
    answer: str | None = None
    memory: dict[str, Any] | None = None  # {"content": str, "memory_type": str}
