"""Real-time voice errors: a stable `code` (see docs/phase17/contract.md), an HTTP
status and a safe message. Internal details never reach the client."""

# code -> (HTTP status, safe message)
ERRORS: dict[str, tuple[int, str]] = {
    "realtime_disabled": (503, "Real-time voice is turned off on this server."),
    "provider_not_configured": (503, "Real-time voice isn't set up on this server."),
    "consent_missing": (409, "Turn on this AI Clone's voice (with voice consent) to use real-time voice."),
    "realtime_off": (409, "Real-time voice is turned off for this AI Clone."),
    "forbidden": (403, "You can't use real-time voice with this AI Clone."),
    "rate_limited": (429, "Too many voice sessions started. Please wait a moment."),
    "too_many_sessions": (409, "You already have a live voice session. End it before starting another."),
    "quota_exceeded": (402, "Your plan's real-time voice sessions for this month are used up."),
    "session_not_found": (404, "Voice session not found."),
    "session_expired": (410, "This voice session has expired. Start a new one."),
    "provider_unavailable": (503, "The voice service is temporarily unavailable. Please try again."),
    "invalid_settings": (422, "Visitors can use real-time voice only while public chat and public voice are on."),
    "invalid_audio": (400, "That recording couldn't be used. Please speak again."),
    "invalid_message": (400, "That message couldn't be used."),
    "signaling_failed": (400, "The voice connection couldn't be set up."),
}


class RealtimeVoiceError(Exception):
    def __init__(self, code: str, message: str | None = None, status_code: int | None = None) -> None:
        default_status, default_message = ERRORS.get(code, (400, "Real-time voice failed."))
        self.code = code
        self.message = message or default_message
        self.status_code = status_code or default_status
        super().__init__(self.message)
