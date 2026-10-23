"""date_time: the current date and time (UTC, or an IANA time zone). No side effects."""

import re
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.agent.exceptions import ToolInputError
from app.agent.schemas import RiskLevel, ToolContext, ToolResult
from app.agent.tool_registry import Tool, register
from app.agent.tools._common import check_object, string_arg

MAX_TIMEZONE = 64
# IANA names look like "UTC", "Asia/Karachi", "America/Argentina/Buenos_Aires", "Etc/GMT+5".
_TZ_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_+\-]*(/[A-Za-z0-9_+\-]+){0,2}$")


def resolve_timezone(name: str) -> ZoneInfo:
    if not _TZ_PATTERN.match(name):
        raise ToolInputError("Unknown time zone. Use an IANA name such as 'Asia/Karachi' or 'UTC'.")
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        raise ToolInputError("Unknown time zone. Use an IANA name such as 'Asia/Karachi' or 'UTC'.") from None


class DateTimeTool(Tool):
    name = "date_time"
    title = "Date and time"
    description = (
        "Get the current date, time and weekday in UTC, or in an IANA time zone if given "
        "(e.g. 'Asia/Karachi', 'Europe/London'). Use it for questions about today, now or dates."
    )
    permission_scope = "utility:read"
    risk = RiskLevel.LOW
    timeout_seconds = 2.0
    enabled_by_default = True
    confirmation_by_default = False
    public_safe = True
    input_schema = {
        "type": "object",
        "properties": {"timezone": {"type": "string", "minLength": 1, "maxLength": MAX_TIMEZONE}},
        "additionalProperties": False,
    }
    output_schema = {
        "type": "object",
        "properties": {
            "timezone": {"type": "string"},
            "datetime": {"type": "string", "description": "ISO 8601 in that time zone"},
            "utc": {"type": "string"},
            "date": {"type": "string"},
            "time": {"type": "string"},
            "weekday": {"type": "string"},
            "utc_offset": {"type": "string"},
        },
    }

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        check_object(arguments, {"timezone"})
        timezone = string_arg(arguments, "timezone", max_length=MAX_TIMEZONE, required=False)
        if timezone is not None:
            resolve_timezone(timezone)
        return {"timezone": timezone or "UTC"}

    def run(self, ctx: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        name = arguments.get("timezone") or "UTC"
        now_utc = datetime.now(UTC).replace(microsecond=0)
        local = now_utc.astimezone(resolve_timezone(name)) if name != "UTC" else now_utc
        offset = local.strftime("%z")
        data = {
            "timezone": name,
            "datetime": local.isoformat(),
            "utc": now_utc.isoformat(),
            "date": local.date().isoformat(),
            "time": local.strftime("%H:%M:%S"),
            "weekday": local.strftime("%A"),
            "utc_offset": f"{offset[:3]}:{offset[3:]}" if offset else "+00:00",
        }
        return ToolResult(ok=True, data=data, summary=f"Checked the current date and time ({name})")


register(DateTimeTool())
