"""The developer API's error format.

Every /api/v1 error is JSON {"error": code, "message": text, "request_id": "req_..."}
(plus "retry_after" for 429). Codes are stable; messages are for humans.
"""

ERROR_CODES = {
    400: "invalid_request",
    401: "authentication_failed",
    403: "permission_denied",
    404: "resource_not_found",
    409: "invalid_request",
    413: "invalid_request",
    415: "invalid_request",
    422: "validation_error",
    429: "rate_limit_exceeded",
    502: "provider_unavailable",
    503: "provider_unavailable",
    504: "provider_unavailable",
}


def code_for(status: int) -> str:
    return ERROR_CODES.get(status, "internal_error" if status >= 500 else "invalid_request")


class ApiError(Exception):
    """An error raised by developer API code with an explicit code."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        retry_after: int | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.retry_after = retry_after
        self.headers = headers or {}


def is_developer_api(path: str) -> bool:
    return path.startswith("/api/v1/") or path == "/api/v1"
