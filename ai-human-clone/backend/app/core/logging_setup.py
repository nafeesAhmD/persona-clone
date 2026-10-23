"""Logging: readable text (default) or one JSON object per line (LOG_FORMAT=json).

Every record carries the current request id (from RequestIdMiddleware), so a line in
the logs can be matched with the X-Request-ID a user reports. Messages are logged as
written: the code never puts passwords, tokens, keys or document text in them, and
uvicorn's WebSocket ticket is redacted by a filter (app/realtime_voice/safety.py).
"""

import json
import logging
from contextvars import ContextVar
from datetime import UTC, datetime

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

TEXT_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = getattr(record, "request_id", None) or request_id_var.get()
        if request_id:
            entry["request_id"] = request_id
        for key in ("method", "route", "status", "duration_ms"):
            if hasattr(record, key):
                entry[key] = getattr(record, key)
        if record.exc_info:
            # The type and the trace stay in the server logs; never sent to clients.
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO", log_format: str = "text") -> None:
    """Configure the root logger once (replaces logging.basicConfig)."""
    handler = logging.StreamHandler()
    if log_format.strip().lower() == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(TEXT_FORMAT))
    handler.addFilter(RequestIdFilter())
    root = logging.getLogger()
    for existing in list(root.handlers):
        if getattr(existing, "_ahc_handler", False):
            root.removeHandler(existing)
    handler._ahc_handler = True  # type: ignore[attr-defined]
    root.addHandler(handler)
    root.setLevel(level.upper())
    if log_format.strip().lower() == "json":
        # Uvicorn's own lines go through the same JSON handler instead of its text one.
        for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
            uvicorn_logger = logging.getLogger(name)
            uvicorn_logger.handlers.clear()
            uvicorn_logger.propagate = True
