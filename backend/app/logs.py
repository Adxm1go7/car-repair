"""JSON logs: every line is one JSON object, for both the API and the worker.

Each line has `time` (UTC), `level`, `logger` and `message`, plus any fields passed with
`extra=`, plus `error` (the traceback) when there's an exception. Customer emails, phones,
tokens and query strings never go in a log line: log a booking reference or an id instead.
"""

import json
import logging
import sys
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

# The attributes every LogRecord has; anything else on a record came from `extra=`.
_STANDARD = set(vars(logging.LogRecord("", 0, "", 0, "", (), None))) | {"message", "asctime"}
_STANDARD.add("color_message")  # uvicorn's copy of the message with terminal colours

request_log = logging.getLogger("app.request")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        line: dict[str, Any] = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        line.update({k: v for k, v in vars(record).items() if k not in _STANDARD})
        if record.exc_info:
            line["error"] = self.formatException(record.exc_info)
        return json.dumps(line, default=str)


def configure_logging(level: int = logging.INFO) -> None:
    """Send every logger's lines, uvicorn's included, through one JSON handler on stdout.
    Safe to call twice: an earlier JSON handler is replaced, other handlers are left alone
    (pytest's capture, for one)."""
    root = logging.getLogger()
    for handler in root.handlers[:]:
        if isinstance(handler.formatter, JsonFormatter):
            root.removeHandler(handler)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level)
    for name in ("uvicorn", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
    # uvicorn writes access lines whenever this logger has any handler, a parent's included.
    # They'd carry the query string, and `app.request` already logs every request.
    access = logging.getLogger("uvicorn.access")
    access.handlers.clear()
    access.propagate = False


class RequestLogMiddleware:
    """One `app.request` line per HTTP request, with a request id also sent back in
    `X-Request-ID`. Pure ASGI, so the body (the Stripe webhook's signed one) is never read."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = uuid.uuid4().hex
        status = 500  # if no response starts, the request failed
        started = time.perf_counter()

        async def send_with_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode()))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            request_log.info(
                "request",
                extra={
                    "method": scope["method"],
                    "path": scope["path"],  # never the query string: it can hold an email
                    "status": status,
                    "duration_ms": round((time.perf_counter() - started) * 1000),
                    "request_id": request_id,
                },
            )
