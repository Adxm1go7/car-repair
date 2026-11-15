"""Booking links: a private token opens one booking until a week after it ends."""

from datetime import UTC, datetime, timedelta

import pytest
from factories import make_hold
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.bookings.links import LINK_VALID_AFTER_END, create_link, find_linked_booking
from app.models import Booking, BookingLink
from app.seed import seed

NOW = datetime(2026, 11, 9, 9, tzinfo=UTC)
START = datetime(2026, 11, 10, 8, tzinfo=UTC)


@pytest.fixture
def seeded(db_session: Session) -> Session:
    seed(db_session)
    return db_session


@pytest.fixture
def booking(seeded: Session) -> Booking:
    return make_hold(seeded, START, NOW + timedelta(minutes=10), status="confirmed")


def test_new_link_opens_its_booking(seeded: Session, booking: Booking) -> None:
    token = create_link(seeded, booking)
    assert find_linked_booking(seeded, booking.reference, token, NOW) is booking


def test_locked_lookup_opens_its_booking(seeded: Session, booking: Booking) -> None:
    token = create_link(seeded, booking)
    found = find_linked_booking(seeded, booking.reference, token, NOW, lock=True)
    assert found is not None
    assert found.id == booking.id


def test_two_links_for_one_booking_both_work(seeded: Session, booking: Booking) -> None:
    first = create_link(seeded, booking)
    second = create_link(seeded, booking)
    assert first != second
    assert find_linked_booking(seeded, booking.reference, first, NOW) is booking
    assert find_linked_booking(seeded, booking.reference, second, NOW) is booking


def test_expired_link_is_none(seeded: Session, booking: Booking) -> None:
    token = create_link(seeded, booking)
    expires = booking.end_at + LINK_VALID_AFTER_END
    assert find_linked_booking(seeded, booking.reference, token, expires) is None
    before = expires - timedelta(seconds=1)
    assert find_linked_booking(seeded, booking.reference, token, before) is booking


def test_wrong_token_is_none(seeded: Session, booking: Booking) -> None:
    create_link(seeded, booking)
    assert find_linked_booking(seeded, booking.reference, "not-the-token", NOW) is None


def test_link_for_another_reference_is_none(seeded: Session, booking: Booking) -> None:
    other = make_hold(seeded, START + timedelta(hours=3), NOW + timedelta(minutes=10))
    token = create_link(seeded, booking)
    assert find_linked_booking(seeded, other.reference, token, NOW) is None


def test_only_the_hash_is_stored(seeded: Session, booking: Booking) -> None:
    token = create_link(seeded, booking)
    (link,) = seeded.scalars(select(BookingLink))
    stored = [getattr(link, column.key) for column in BookingLink.__table__.columns]
    assert token not in stored
    assert link.expires_at == booking.end_at + LINK_VALID_AFTER_END


def test_oversized_token_is_none(seeded: Session, booking: Booking) -> None:
    create_link(seeded, booking)
    assert find_linked_booking(seeded, booking.reference, "x" * 500, NOW) is None
