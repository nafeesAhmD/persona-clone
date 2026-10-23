"""Which tools an agent may use, and whether a call needs the user's confirmation.

Every planner tool call goes through check_tool_call() before it runs. Rules:
- Only registered tools exist; forbidden names (shell, exec, sql...) are never allowed.
- A tool that isn't available() on this server (e.g. web_search without
  AGENT_WEB_SEARCH_ENABLED and a provider) is never enabled, whatever the row says.
- A missing AgentToolPermission row means the tool's defaults, which are conservative:
  a tool is on by default only if it says so AND its risk is low; medium/high/critical
  tools start off and require confirmation.
- Public (visitor) runs may only use tools marked public_safe.
- needs_confirmation = the row's (or default) require_confirmation
  OR tool.confirmation_by_default
  OR (risk >= medium AND (AGENT_DEFAULT_CONFIRMATION_REQUIRED or the agent's
      require_confirmation_for_actions)).
"""

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent import tool_registry
from app.agent.exceptions import ToolNotAllowedError, ToolNotFoundError
from app.agent.schemas import RiskLevel
from app.agent.tool_registry import FORBIDDEN_NAMES, Tool
from app.core.config import get_settings
from app.models.agent import AgentProfile, AgentToolPermission


class ToolSetting(BaseModel):
    name: str
    title: str
    description: str
    risk: str
    permission_scope: str
    enabled: bool
    require_confirmation: bool
    available: bool
    reason_unavailable: str | None = None


def _risky(tool: Tool) -> bool:
    return RiskLevel(tool.risk).rank >= RiskLevel.MEDIUM.rank


def default_enabled(tool: Tool) -> bool:
    return bool(tool.enabled_by_default) and not _risky(tool)


def default_confirmation(tool: Tool) -> bool:
    return bool(tool.confirmation_by_default) or _risky(tool)


def _needs_confirmation(tool: Tool, row: AgentToolPermission | None, profile: AgentProfile) -> bool:
    stored = row.require_confirmation if row is not None else default_confirmation(tool)
    if stored or tool.confirmation_by_default:
        return True
    if _risky(tool):
        return bool(get_settings().agent_default_confirmation_required or profile.require_confirmation_for_actions)
    return False


def _is_enabled(tool: Tool, row: AgentToolPermission | None, available: bool) -> bool:
    if not available or tool.name in FORBIDDEN_NAMES:
        return False
    return bool(row.enabled) if row is not None else default_enabled(tool)


def _rows(db: Session, profile: AgentProfile) -> dict[str, AgentToolPermission]:
    return {
        row.tool_name: row
        for row in db.scalars(select(AgentToolPermission).where(AgentToolPermission.agent_id == profile.id))
    }


def _setting(tool: Tool, row: AgentToolPermission | None, profile: AgentProfile) -> ToolSetting:
    available, reason = tool.available()
    return ToolSetting(
        name=tool.name,
        title=tool.title,
        description=tool.description,
        risk=RiskLevel(tool.risk).value,
        permission_scope=tool.permission_scope,
        enabled=_is_enabled(tool, row, available),
        require_confirmation=_needs_confirmation(tool, row, profile),
        available=available,
        reason_unavailable=None if available else (reason or "Not available on this server."),
    )


def effective_tools(db: Session, profile: AgentProfile) -> list[ToolSetting]:
    """Every registered tool with this agent's effective switch (sorted by name)."""
    rows = _rows(db, profile)
    return [_setting(tool, rows.get(tool.name), profile) for tool in tool_registry.all_tools()]


def _lookup(tool_name: object) -> Tool:
    if not isinstance(tool_name, str) or not tool_name or len(tool_name) > 60:
        raise ToolNotFoundError("Unknown tool.")
    if tool_name in FORBIDDEN_NAMES:
        raise ToolNotAllowedError(f"The tool '{tool_name}' is never allowed.")
    return tool_registry.get(tool_name)


def set_tool(
    db: Session, profile: AgentProfile, tool_name: str, enabled: bool, require_confirmation: bool
) -> ToolSetting:
    """Turn one tool on/off for this agent. Raises ToolNotFoundError / ToolNotAllowedError."""
    try:
        tool = _lookup(tool_name)
    except ToolNotAllowedError:
        raise ToolNotFoundError("Unknown tool.") from None
    available, reason = tool.available()
    if enabled and not available:
        raise ToolNotAllowedError(reason or f"The tool '{tool.name}' is not available on this server.")
    row = db.scalar(
        select(AgentToolPermission).where(
            AgentToolPermission.agent_id == profile.id, AgentToolPermission.tool_name == tool.name
        )
    )
    if row is None:
        row = AgentToolPermission(agent_id=profile.id, tool_name=tool.name)
        db.add(row)
    row.enabled = bool(enabled)
    row.require_confirmation = bool(require_confirmation)
    db.commit()
    return _setting(tool, row, profile)


def check_tool_call(db: Session, profile: AgentProfile, tool_name: str, *, source: str) -> tuple[Tool, bool]:
    """May this agent call this tool now? Returns (tool, needs_confirmation).

    Raises ToolNotFoundError (unknown) or ToolNotAllowedError (forbidden, unavailable,
    turned off, or not allowed on public runs)."""
    tool = _lookup(tool_name)
    available, _ = tool.available()
    if not available:
        raise ToolNotAllowedError(f"The tool '{tool.name}' is not available on this server.")
    row = db.scalar(
        select(AgentToolPermission).where(
            AgentToolPermission.agent_id == profile.id, AgentToolPermission.tool_name == tool.name
        )
    )
    if not _is_enabled(tool, row, available):
        raise ToolNotAllowedError(f"The tool '{tool.name}' is turned off for this agent.")
    if source == "public" and not tool.public_safe:
        raise ToolNotAllowedError(f"The tool '{tool.name}' is not available to public visitors.")
    return tool, _needs_confirmation(tool, row, profile)
