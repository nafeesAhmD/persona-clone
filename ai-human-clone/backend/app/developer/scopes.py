"""API key permissions. A key gets only the scopes chosen when it is created."""

SCOPES: dict[str, str] = {
    "clone:read": "List and read your AI Clones (public profile fields only).",
    "clone:chat": "Chat with your AI Clones.",
    "clone:knowledge:read": "Search knowledge marked public.",
    "clone:search": "Search all of a clone's knowledge, including private documents.",
    "conversation:read": "Read API conversations and their messages.",
    "conversation:write": "Delete conversations.",
    "voice:transcribe": "Speech to text.",
    "voice:tts": "Text to speech (and spoken chat answers).",
    "avatar:generate": "Create talking-avatar videos.",
    "analytics:read": "Read clone analytics (counts only, never message content).",
    "agent:run": "Start AI agent runs (the agent uses only the tools the owner turned on).",
    "agent:read": "Read the status, steps and results of AI agent runs started through the API.",
}


def unknown_scopes(scopes: list[str]) -> list[str]:
    return [scope for scope in scopes if scope not in SCOPES]
