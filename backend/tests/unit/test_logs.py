"""Every log line is one JSON object with the standard keys and any extra fields."""

import json
import logging
import sys

from app.logs import JsonFormatter, configure_logging


def record(message: str, *args: object, **extra: object) -> logging.LogRecord:
    rec = logging.LogRecord("t", logging.INFO, __file__, 1, message, args, None)
    for key, value in extra.items():
        setattr(rec, key, value)
    return rec


def test_line_is_json_with_standard_keys() -> None:
    line = json.loads(JsonFormatter().format(record("hello %s", "there")))
    assert line["message"] == "hello there"
    assert line["level"] == "INFO"
    assert line["logger"] == "t"
    assert line["time"].endswith("+00:00")


def test_extra_fields_are_included() -> None:
    line = json.loads(JsonFormatter().format(record("done", job="email", count=3)))
    assert line["job"] == "email"
    assert line["count"] == 3


def test_values_that_are_not_json_become_strings() -> None:
    line = json.loads(JsonFormatter().format(record("done", thing={1, 2})))
    assert isinstance(line["thing"], str)


def test_exception_adds_error() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        rec = logging.LogRecord("t", logging.ERROR, __file__, 1, "failed", (), sys.exc_info())
    output = JsonFormatter().format(rec)
    assert "\n" not in output
    assert "ValueError" in json.loads(output)["error"]


def test_configure_twice_keeps_one_handler() -> None:
    root = logging.getLogger()
    saved = root.handlers[:]
    try:
        configure_logging()
        configure_logging()
        ours = [h for h in root.handlers if isinstance(h.formatter, JsonFormatter)]
        assert len(ours) == 1
        assert logging.getLogger("uvicorn.error").handlers == []
        assert logging.getLogger("uvicorn.error").propagate is True
    finally:
        root.handlers[:] = saved


def test_uvicorn_access_log_stays_off() -> None:
    """uvicorn writes access lines whenever this logger has any handler, a parent's
    included; they'd carry the query string, and `app.request` already covers requests."""
    root = logging.getLogger()
    saved = root.handlers[:]
    try:
        configure_logging()
        assert logging.getLogger("uvicorn.access").hasHandlers() is False
    finally:
        root.handlers[:] = saved


def test_uvicorns_colour_copy_is_dropped() -> None:
    line = json.loads(JsonFormatter().format(record("running", color_message="\x1b[1mrunning")))
    assert "color_message" not in line
