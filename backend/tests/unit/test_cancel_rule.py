"""A customer can cancel a confirmed booking until the free-cancellation window closes."""

from datetime import UTC, datetime, timedelta

from app.bookings.rules import customer_can_cancel

START = datetime(2026, 11, 20, 9, tzinfo=UTC)
HOURS = 24


def test_exactly_24_hours_before_can_cancel() -> None:
    assert customer_can_cancel("confirmed", START, START - timedelta(hours=HOURS), HOURS)


def test_one_second_inside_the_window_cannot() -> None:
    now = START - timedelta(hours=HOURS) + timedelta(seconds=1)
    assert not customer_can_cancel("confirmed", START, now, HOURS)


def test_cancelled_cannot() -> None:
    assert not customer_can_cancel("cancelled", START, START - timedelta(days=5), HOURS)
