"""Agent errors. Messages are safe to show; details stay in logs."""


class AgentError(Exception):
    """Base class."""


class AgentDisabledError(AgentError):
    """The agent (platform-wide or for this clone) is turned off."""


class ToolNotFoundError(AgentError):
    """No such registered tool."""


class ToolNotAllowedError(AgentError):
    """The tool exists but this agent/caller may not use it (disabled, scope, public run...)."""


class ToolInputError(AgentError):
    """The arguments don't match the tool's input schema."""


class ToolExecutionError(AgentError):
    """The tool failed (safe message)."""


class AgentLimitError(AgentError):
    """A step, tool-call, time or plan limit was reached."""


class ConfirmationError(AgentError):
    """A confirmation/rejection doesn't match the pending action (wrong, stale or replayed)."""
