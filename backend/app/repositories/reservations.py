"""Reserve a slot in a bay. The engine's check is advisory; the database constraint decides."""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Reservation, Service
from app.repositories.availability import day_availability, load_policy

EXCLUSION_VIOLATION = "23P01"


class SlotUnavailable(Exception):
    """No bay can take this start any more."""


@dataclass(frozen=True)
class ReserveResult:
    """The inserted reservation, plus the customer-facing local start and real end."""

    reservation: Reservation
    start: datetime
    end: datetime


def reserve(
    session: Session,
    service_ids: Sequence[int],
    start: datetime,
    now: datetime,
    cutoff_minutes: int | None = None,
) -> ReserveResult:
    """Insert a booking reservation for `start` in the first bay that takes it.

    Doesn't check the booking window or past dates; callers do. Doesn't commit.
    `cutoff_minutes` replaces the setting when given, so staff tools can pass 0.
    """
    if start.tzinfo is None or start.utcoffset() is None:
        raise ValueError("start must be timezone-aware")
    wanted = set(service_ids)
    services = list(
        session.scalars(select(Service).where(Service.id.in_(wanted), Service.active.is_(True)))
    )
    if not wanted or len(services) != len(wanted):
        raise ValueError("Unknown or inactive service")

    policy = load_policy(session)
    if cutoff_minutes is not None:
        policy = replace(policy, cutoff_minutes=cutoff_minutes)
    day = start.astimezone(policy.zone).date()
    availability = day_availability(session, services, day, now, policy)
    # Compare in UTC. Two times with the same tzinfo compare by wall clock and ignore `fold`,
    # so the second 01:30 on a clock-change day would otherwise match the first.
    wanted_start = start.astimezone(UTC)
    slot = next((s for s in availability.slots if s.start.astimezone(UTC) == wanted_start), None)
    if slot is None:
        raise SlotUnavailable

    # Add the buffer in UTC: adding to a local time would follow the wall clock.
    occupied_until = slot.end.astimezone(UTC) + timedelta(minutes=policy.buffer_minutes)
    during = Range(slot.start.astimezone(UTC), occupied_until)
    for bay_id in slot.bay_ids:
        reservation = Reservation(bay_id=bay_id, kind="booking", during=during)
        try:
            with session.begin_nested():
                session.add(reservation)
                session.flush()
        except IntegrityError as error:
            if getattr(error.orig, "sqlstate", None) != EXCLUSION_VIOLATION:
                raise
            continue  # someone else took this bay since the engine looked; try the next one
        return ReserveResult(reservation=reservation, start=slot.start, end=slot.end)
    raise SlotUnavailable
