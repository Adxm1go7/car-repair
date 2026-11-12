"""Holding a slot for a customer. Routes call these; they call the repositories.

Nothing here commits: the caller decides when the work is done.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.bookings.rules import hash_token, new_hold_token, new_reference
from app.models import Booking, BookingItem, Service
from app.repositories.bookings import release_expired_holds
from app.repositories.reservations import reserve

REFERENCE_ATTEMPTS = 3
REFERENCE_CONSTRAINT = "uq_bookings_reference"


@dataclass(frozen=True)
class HoldCreated:
    booking: Booking
    token: str  # the only time the plain token exists; the database keeps its hash


def create_hold(
    session: Session,
    services: Sequence[Service],
    start: datetime,
    now: datetime,
    hold_minutes: int,
) -> HoldCreated:
    """Reserve `start` for these services and record a held booking. Raises SlotUnavailable.

    Expired holds are released first: their reservations are still active until something
    flips them, and the overlap constraint would otherwise refuse the new one.
    """
    release_expired_holds(session, now)
    reserved = reserve(session, [service.id for service in services], start, now)

    token = new_hold_token()
    for attempt in range(REFERENCE_ATTEMPTS):
        items = [
            BookingItem(
                service_id=service.id,
                service_name=service.name,
                price_from_pence=service.price_from_pence,
                price_to_pence=service.price_to_pence,
                duration_minutes=service.duration_minutes,
                position=position,
            )
            for position, service in enumerate(services)
        ]
        booking = Booking(
            reference=new_reference(),
            reservation=reserved.reservation,
            status="held",
            start_at=reserved.start,
            end_at=reserved.end,
            hold_expires_at=now + timedelta(minutes=hold_minutes),
            hold_token_hash=hash_token(token),
            items=items,
        )
        try:
            with session.begin_nested():
                session.add(booking)
                session.flush()
        except IntegrityError as error:
            constraint = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
            if constraint != REFERENCE_CONSTRAINT or attempt == REFERENCE_ATTEMPTS - 1:
                raise
            continue  # the reference is taken (very rare): try another
        return HoldCreated(booking=booking, token=token)
    raise AssertionError("unreachable")  # pragma: no cover


def summary_services(booking: Booking) -> list[dict[str, object]]:
    """The services on a booking, from the snapshots taken when it was made."""
    return [
        {
            "slug": item.service.slug,
            "name": item.service_name,
            "duration_minutes": item.duration_minutes,
            "price_from_pence": item.price_from_pence,
            "price_to_pence": item.price_to_pence,
        }
        for item in booking.items
    ]
