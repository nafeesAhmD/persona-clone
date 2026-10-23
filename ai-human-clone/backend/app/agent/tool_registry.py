"""The central tool registry: the only things an agent can ever do.

Each tool declares its name, description, JSON input/output schemas, permission scope,
risk level, timeout and defaults. Tools live in app/agent/tools/*.py and register
themselves via `register()` when app.agent.tools is imported.

Never register a generic command, code, shell, filesystem, environment or database
tool (execute_command, run_python, run_shell, read_env, database_query...).
"""

from abc import ABC, abstractmethod
from typing import Any

from app.agent.exceptions import ToolNotFoundError
from app.agent.schemas import RiskLevel, ToolContext, ToolResult

FORBIDDEN_NAMES = frozenset(
    {"execute_command", "run_python", "run_shell", "shell", "exec", "eval", "read_env", "database_query", "sql"}
)


class Tool(ABC):
    name: str
    title: str  # human label for the settings UI
    description: str  # what the planner is told the tool does
    permission_scope: str  # e.g. "knowledge:read"
    risk: RiskLevel = RiskLevel.LOW
    timeout_seconds: float = 15.0
    input_schema: dict[str, Any] = {"type": "object", "properties": {}, "additionalProperties": False}
    output_schema: dict[str, Any] = {"type": "object"}
    # Defaults when an agent has no explicit permission row for this tool.
    enabled_by_default: bool = True
    confirmation_by_default: bool = False
    # May be offered to public (visitor) runs if a public agent is ever enabled.
    public_safe: bool = False

    def available(self) -> tuple[bool, str | None]:
        """(usable on this server?, reason if not) — e.g. web search needs AGENT_WEB_SEARCH_ENABLED."""
        return True, None

    @abstractmethod
    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Check arguments against input_schema; return cleaned arguments or raise ToolInputError."""

    @abstractmethod
    def run(self, ctx: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        """Do the work (synchronous; the executor applies the timeout). Never raise secrets."""


_REGISTRY: dict[str, Tool] = {}


def register(tool: Tool) -> Tool:
    if tool.name in FORBIDDEN_NAMES:
        raise ValueError(f"Tool name {tool.name!r} is not allowed")
    _REGISTRY[tool.name] = tool
    return tool


def get(name: str) -> Tool:
    _load()
    tool = _REGISTRY.get(name)
    if tool is None:
        raise ToolNotFoundError(f"Unknown tool: {name}")
    return tool


def all_tools() -> list[Tool]:
    _load()
    return sorted(_REGISTRY.values(), key=lambda t: t.name)


def _load() -> None:
    # Importing the package registers every built-in tool exactly once.
    import app.agent.tools  # noqa: F401
