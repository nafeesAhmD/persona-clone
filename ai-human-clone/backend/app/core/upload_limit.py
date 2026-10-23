"""Reject oversized uploads before the request body is read.

The storage layer also enforces the limit while copying, but checking the
Content-Length header first means a 1 GB upload is refused immediately instead
of being parsed and spooled to disk.
"""

import re

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import get_settings

_UPLOAD_PATH = re.compile(r"^/api/clones/[^/]+/documents/?$")
_VOICE_PATH = re.compile(r"^/api/(clones/[^/]+/voice/(transcribe|chat)|public/clones/[^/]+/voice/transcribe)/?$")
_AVATAR_PATH = re.compile(r"^/api/clones/[^/]+/avatar/?$")
# Room for multipart boundaries and the other form fields.
_MULTIPART_OVERHEAD = 64 * 1024


def too_large_message() -> str:
    return f"File is too large. Maximum allowed size is {get_settings().max_upload_size_mb} MB."


class UploadSizeLimitMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    @staticmethod
    def _limit_for(scope: Scope) -> tuple[int | None, str]:
        if scope["type"] != "http" or scope["method"] != "POST":
            return None, ""
        settings = get_settings()
        if _UPLOAD_PATH.match(scope["path"]):
            return settings.max_upload_size_mb, too_large_message()
        if _AVATAR_PATH.match(scope["path"]):
            return settings.max_avatar_size_mb, f"The image is too large. Maximum size is {settings.max_avatar_size_mb} MB."
        if _VOICE_PATH.match(scope["path"]):
            return settings.max_audio_size_mb, f"The recording is too large. Maximum size is {settings.max_audio_size_mb} MB."
        return None, ""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        limit_mb, message = self._limit_for(scope)
        if limit_mb is not None:
            headers = dict(scope["headers"])
            length = headers.get(b"content-length")
            limit = limit_mb * 1024 * 1024 + _MULTIPART_OVERHEAD
            if length is not None and length.isdigit() and int(length) > limit:
                response = JSONResponse(status_code=413, content={"detail": message})
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)
