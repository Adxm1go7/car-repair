"""When a hold counts as expired. Exactly at its expiry time it has expired."""

from datetime import UTC, datetime, timedelta

from app.models import Booking
from app.repositories.bookings import hold_has_expired

EXPIRES = datetime(2026, 11, 9, 9, 10, tzinfo=UTC)


def booking(status: str = "held") -> Booking:
    return Booking(status=status, hold_expires_at=EXPIRES)


def test_hold_expired_exactly_at_expiry() -> None:
    assert hold_has_expired(booking(), EXPIRES)


def test_hold_not_expired_one_second_before() -> None:
    assert not hold_has_expired(booking(), EXPIRES - timedelta(seconds=1))


def test_confirmed_booking_never_expired() -> None:
    assert not hold_has_expired(booking("confirmed"), EXPIRES + timedelta(days=1))


def test_already_expired_booking_is_not_a_hold_to_expire_again() -> None:
    # "Expired" here means a held booking past its time; one already released isn't held.
    assert not hold_has_expired(booking("expired"), EXPIRES + timedelta(days=1))
