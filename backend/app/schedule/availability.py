"""The free times staff see when moving a booking or booking a phone customer.

The same engine as the public site, with two differences: no cut-off before a slot, and
no booking window (no caller checks it). Opening hours, breaks, blocks, other bookings,
bay types and the bay buffer all still apply.
"""

from collections.abc import Sequence
from dataclasses import replace
from datetime import date, datetime

from sqlalchemy.orm import Session

from app.availability.engine import DayAvailability, Policy, ServiceInfo
from app.models import Booking, Service
from app.repositories.availability import day_availability_for, load_policy


def staff_policy(session: Session) -> Policy:
    return replace(load_policy(session), cutoff_minutes=0)


def infos_for_services(services: Sequence[Service]) -> list[ServiceInfo]:
    return [ServiceInfo(s.id, s.duration_minutes, s.required_bay_type_id) for s in services]


def infos_for_booking(booking: Booking) -> list[ServiceInfo]:
    """The booking's own job: durations as saved when it was booked, not today's."""
    return [
        ServiceInfo(item.service_id, item.duration_minutes, item.service.required_bay_type_id)
        for item in booking.items
    ]


def staff_free_times(
    session: Session,
    infos: Sequence[ServiceInfo],
    day: date,
    now: datetime,
    *,
    exclude_reservation_id: int | None = None,
) -> DayAvailability:
    return day_availability_for(
        session,
        infos,
        day,
        now,
        staff_policy(session),
        exclude_reservation_id=exclude_reservation_id,
    )
