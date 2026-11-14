"""Test data builders shared by several test files."""

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.orm import Session

from app.bookings.rules import hash_token, new_reference
from app.models import Bay, Booking, Payment, Reservation

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
    details: bool = False,
) -> Booking:
    """A one-hour booking at `start` (aware, any zone) with its reservation, flushed.

    Its token is TEST_TOKEN. A "confirmed" booking gets customer details and a paid deposit,
    so it's valid. `details=True` gives any booking them, as if payment had started.
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
        **(CUSTOMER if status == "confirmed" or details else {}),
        deposit_status="paid" if status == "confirmed" else "unpaid",
    )
    session.add(booking)
    session.flush()
    return booking


def make_deposit(
    session: Session,
    booking: Booking,
    *,
    ref: str = "cs_test_1",
    status: str = "open",
    amount_pence: int = 2000,
    provider: str = "stripe",
) -> Payment:
    """A deposit payment row for `booking`, flushed."""
    payment = Payment(
        booking_id=booking.id,
        kind="deposit",
        provider=provider,
        provider_ref=ref,
        amount_pence=amount_pence,
        status=status,
    )
    session.add(payment)
    session.flush()
    return payment
