"""The current time, as a FastAPI dependency so tests can pin it."""

from datetime import UTC, datetime


def utc_now() -> datetime:
    return datetime.now(UTC)
