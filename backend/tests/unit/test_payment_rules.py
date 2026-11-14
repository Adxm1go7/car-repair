"""The free-cancellation rule: refund when the customer cancels in time, always for the garage."""

from datetime import UTC, datetime, timedelta

from app.payments.rules import deposit_refundable

START = datetime(2026, 11, 20, 9, tzinfo=UTC)
DAY = timedelta(hours=24)
SECOND = timedelta(seconds=1)


def test_customer_exactly_at_the_boundary_is_refunded() -> None:
    assert deposit_refundable(START, START - DAY, 24, "customer") is True


def test_customer_one_second_late_is_not_refunded() -> None:
    assert deposit_refundable(START, START - DAY + SECOND, 24, "customer") is False


def test_customer_well_ahead_is_refunded() -> None:
    assert deposit_refundable(START, START - DAY - SECOND, 24, "customer") is True


def test_garage_always_refunds() -> None:
    assert deposit_refundable(START, START - timedelta(minutes=5), 24, "garage") is True
    assert deposit_refundable(START, START + DAY, 24, "garage") is True


def test_no_window_refunds_until_the_start() -> None:
    assert deposit_refundable(START, START - SECOND, 0, "customer") is True
    assert deposit_refundable(START, START + SECOND, 0, "customer") is False
