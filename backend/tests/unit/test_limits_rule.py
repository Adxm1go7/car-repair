"""How long a visitor over a rate limit is told to wait."""

from datetime import UTC, datetime, timedelta

from app.limits import retry_after

T = datetime(2026, 11, 20, 9, tzinfo=UTC)
WINDOW = timedelta(minutes=15)


def test_retry_after() -> None:
    assert retry_after(T, WINDOW, T) == 900
    assert retry_after(T, WINDOW, T + timedelta(minutes=10)) == 300
    assert retry_after(T, WINDOW, T + timedelta(minutes=14, seconds=59.5)) == 1


def test_retry_after_is_never_below_one() -> None:
    assert retry_after(T, WINDOW, T + WINDOW) == 1
    assert retry_after(T, WINDOW, T + timedelta(hours=1)) == 1
