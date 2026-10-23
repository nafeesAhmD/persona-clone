"""clone_info: the clone's public-facing profile fields.

An explicit allowlist: name, profession, tagline, skills, preferred language,
communication style and public status. Never the system prompt, personality
internals, bio, owner details (email), keys, voice/avatar settings or ids.
"""

from typing import Any

from app.agent.schemas import RiskLevel, ToolContext, ToolResult
from app.agent.tool_registry import Tool, register
from app.agent.tools._common import check_object, truncate

MAX_SKILLS = 30


class CloneInfoTool(Tool):
    name = "clone_info"
    title = "Clone profile"
    description = (
        "Get the clone's basic profile: name, profession, tagline, skills, preferred language, "
        "communication style and whether it is public. Takes no arguments."
    )
    permission_scope = "clone:read"
    risk = RiskLevel.LOW
    timeout_seconds = 5.0
    enabled_by_default = True
    confirmation_by_default = False
    public_safe = False
    input_schema = {"type": "object", "properties": {}, "additionalProperties": False}
    output_schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "profession": {"type": ["string", "null"]},
            "tagline": {"type": ["string", "null"]},
            "skills": {"type": "array", "items": {"type": "string"}},
            "preferred_language": {"type": ["string", "null"]},
            "communication_style": {"type": ["string", "null"]},
            "public": {
                "type": "object",
                "properties": {
                    "visibility": {"type": "string"},
                    "public_chat_enabled": {"type": "boolean"},
                    "status": {"type": "string"},
                },
            },
        },
    }

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        check_object(arguments, set())
        return {}

    def run(self, ctx: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        clone = ctx.clone
        skills = [truncate(str(skill), 80) for skill in (clone.skills or []) if str(skill).strip()][:MAX_SKILLS]
        data = {
            "name": truncate(clone.name, 120),
            "profession": truncate(clone.profession, 120) or None,
            "tagline": truncate(clone.tagline, 160) or None,
            "skills": skills,
            "preferred_language": truncate(clone.preferred_language, 60) or None,
            "communication_style": truncate(clone.communication_style, 500) or None,
            "public": {
                "visibility": clone.visibility,
                "public_chat_enabled": bool(clone.public_chat_enabled),
                "status": clone.status,
            },
        }
        return ToolResult(ok=True, data=data, summary="Read the clone's profile")


register(CloneInfoTool())
