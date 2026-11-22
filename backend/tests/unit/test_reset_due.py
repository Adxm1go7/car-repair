"""When the live demo's nightly reset is due: once after each 03:00 in London."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from app.demo.reset import reset_due

LONDON = ZoneInfo("Europe/London")


def at(text: str) -> datetime:
    """A London wall-clock time, e.g. "2026-11-21 03:05"."""
    return datetime.fromisoformat(text).replace(tzinfo=LONDON)


@pytest.mark.parametrize(
    ("last", "now", "due"),
    [
        (None, "2026-11-21 03:05", True),  # the worker started just after 03:00
        (None, "2026-11-21 12:00", False),  # a restart at noon doesn't wipe the demo
        (None, "2026-11-21 02:59", False),
        ("2026-11-20 03:00", "2026-11-21 03:00", True),
        ("2026-11-21 03:00", "2026-11-21 23:00", False),
        ("2026-11-21 03:01", "2026-11-22 02:59", False),
        ("2026-03-28 03:00", "2026-03-29 03:00", True),  # clocks went forward at 01:00
        ("2026-10-24 03:00", "2026-10-25 03:00", True),  # clocks went back at 02:00
        ("2026-10-25 03:00", "2026-10-25 04:00", False),
    ],
)
def test_reset_due(last: str | None, now: str, due: bool) -> None:
    last_reset = at(last) if last else None
    assert reset_due(last_reset, at(now).astimezone(UTC), LONDON) is due
