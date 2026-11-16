"""Phone bookings: staff book in a customer who rang. Confirmed at once, with no deposit;
the customer's email is optional. Staff free times apply (no cut-off, no window).
Nothing here commits."""

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.bookings.service import insert_with_reference, snapshot_items
from app.email.queue import queue_email
from app.models import Booking, Service, StaffUser
from app.repositories.reservations import reserve
from app.staff.audit import record_audit


@dataclass(frozen=True)
class PhoneDetails:
    """Already cleaned by the `clean_*` rules."""

    name: str
    phone: str
    email: str | None
    registration: str
    make: str
    model: str
    notes: str | None


def create_phone_booking(
    session: Session,
    staff: StaffUser,
    services: Sequence[Service],
    start: datetime,
    bay_id: int,
    details: PhoneDetails,
    now: datetime,
) -> Booking:
    """Reserve `start` in the chosen bay and record a confirmed booking. Raises
    SlotUnavailable if the bay can't take it."""
    reserved = reserve(
        session, [s.id for s in services], start, now, cutoff_minutes=0, bay_id=bay_id
    )
    booking = insert_with_reference(
        session,
        lambda reference: Booking(
            reference=reference,
            reservation=reserved.reservation,
            status="confirmed",
            source="phone",
            created_by=staff.id,
            start_at=reserved.start,
            end_at=reserved.end,
            confirmed_at=now,
            deposit_status="not_required",
            customer_name=details.name,
            customer_phone=details.phone,
            customer_email=details.email,
            car_registration=details.registration,
            car_make=details.make,
            car_model=details.model,
            notes=details.notes,
            items=snapshot_items(services),
        ),
    )
    queue_email(session, "confirmation", booking)  # nothing when there's no email
    record_audit(
        session,
        staff,
        "booking.create",
        "booking",
        booking.id,
        after={
            "start": booking.start_at.isoformat(),
            "end": booking.end_at.isoformat(),
            "bay_id": bay_id,
            "services": [s.name for s in services],
            **asdict(details),
        },
        booking_reference=booking.reference,
        now=now,
    )
    return booking
