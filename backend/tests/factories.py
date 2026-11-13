"""Test data builders shared by several test files."""

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.orm import Session

from app.bookings.rules import hash_token, new_reference
from app.models import Bay, Booking, Reservation

TEST_TOKEN = "t"  # noqa: S105 - a test hold token, not a password
BUFFER = timedelta(minutes=15)
CUSTOMER = {
    "customer_name": "Sam Driver",
    "customer_phone": "07700 900123",
    "customer_email": "sam@example.com",
    "car_registration": "AB12CDE",
    "car_make": "Ford",
    "car_model": "Focus",
}


def make_hold(
    session: Session,
    start: datetime,
    expires_at: datetime,
    *,
    bay_slug: str = "mot-bay",
    status: str = "held",
) -> Booking:
    """A one-hour booking at `start` (aware, any zone) with its reservation, flushed.

    Its token is TEST_TOKEN. A "confirmed" booking gets customer details so it's valid.
    """
    bay = session.scalars(select(Bay.id).where(Bay.slug == bay_slug)).one()
    end = start + timedelta(hours=1)
    reservation = Reservation(
        bay_id=bay,
        kind="booking",
        during=Range(start, end + BUFFER),
        active=status in ("held", "confirmed"),
    )
    session.add(reservation)
    session.flush()
    booking = Booking(
        reference=new_reference(),
        reservation_id=reservation.id,
        status=status,
        start_at=start,
        end_at=end,
        hold_expires_at=expires_at,
        hold_token_hash=hash_token(TEST_TOKEN),
        **(CUSTOMER if status == "confirmed" else {}),
    )
    session.add(booking)
    session.flush()
    return booking
