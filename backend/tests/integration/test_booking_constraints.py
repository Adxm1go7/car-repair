"""The database refuses bookings that break the rules, whatever the application code does."""

from datetime import UTC, datetime, timedelta
from itertools import count
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Bay, Booking, BookingItem, Reservation, Service
from app.seed import seed

START = datetime(2026, 11, 10, 9, tzinfo=UTC)
END = START + timedelta(hours=1)
DETAILS = {
    "customer_name": "Sam Driver",
    "customer_phone": "07700 900123",
    "customer_email": "sam@example.com",
    "car_registration": "AB12CDE",
    "car_make": "Ford",
    "car_model": "Focus",
}

_numbers = count(1)


def new_reservation(session: Session, n: int) -> Reservation:
    """A reservation in bay 1. Each `n` is two hours later, so none overlap."""
    bay = session.scalars(select(Bay.id).where(Bay.slug == "bay-1")).one()
    start = START + timedelta(hours=2 * n)
    reservation = Reservation(
        bay_id=bay, kind="booking", during=Range(start, start + (END - START))
    )
    session.add(reservation)
    session.flush()
    return reservation


def booking(session: Session, **overrides: Any) -> Booking:
    """A valid held booking with its own reservation and reference, unless overridden."""
    n = next(_numbers)
    values: dict[str, Any] = {
        "reference": f"TEST-{n:04d}",
        "status": "held",
        "start_at": START,
        "end_at": END,
        "hold_expires_at": START - timedelta(minutes=50),
        "hold_token_hash": "0" * 64,
    } | overrides
    if "reservation_id" not in values:
        values["reservation_id"] = new_reservation(session, n).id
    return Booking(**values)


def flush(session: Session, *rows: object) -> None:
    session.add_all(rows)
    session.flush()


def rejected(session: Session, *rows: object) -> None:
    with pytest.raises(IntegrityError), session.begin_nested():
        flush(session, *rows)


@pytest.fixture
def seeded(db_session: Session) -> Session:
    seed(db_session)
    return db_session


def test_held_booking_can_be_stored(seeded: Session) -> None:
    flush(seeded, booking(seeded))


@pytest.mark.parametrize("missing", ["hold_expires_at", "hold_token_hash"])
def test_held_booking_needs_expiry_and_token_hash(seeded: Session, missing: str) -> None:
    rejected(seeded, booking(seeded, **{missing: None}))


def test_confirmed_booking_can_be_stored(seeded: Session) -> None:
    flush(seeded, booking(seeded, status="confirmed", **DETAILS))


@pytest.mark.parametrize("missing", list(DETAILS))
def test_confirmed_booking_needs_customer_details(seeded: Session, missing: str) -> None:
    rejected(seeded, booking(seeded, status="confirmed", **(DETAILS | {missing: None})))


def test_unknown_status_is_rejected(seeded: Session) -> None:
    rejected(seeded, booking(seeded, status="maybe"))


def test_start_must_be_before_end(seeded: Session) -> None:
    rejected(seeded, booking(seeded, end_at=START))


def test_one_booking_per_reservation(seeded: Session) -> None:
    first = booking(seeded)
    flush(seeded, first)
    rejected(seeded, booking(seeded, reservation_id=first.reservation_id, reference="OTHR-0001"))


def test_reference_is_unique(seeded: Session) -> None:
    flush(seeded, booking(seeded, reference="SAME-0001"))
    rejected(seeded, booking(seeded, reference="SAME-0001"))


def test_item_positions_are_unique_per_booking(seeded: Session) -> None:
    held = booking(seeded)
    flush(seeded, held)
    mot = seeded.scalars(select(Service).where(Service.slug == "mot-test")).one()

    def item(position: int) -> BookingItem:
        return BookingItem(
            booking_id=held.id,
            service_id=mot.id,
            service_name=mot.name,
            price_from_pence=mot.price_from_pence,
            price_to_pence=None,
            duration_minutes=mot.duration_minutes,
            position=position,
        )

    flush(seeded, item(0))
    rejected(seeded, item(0))
