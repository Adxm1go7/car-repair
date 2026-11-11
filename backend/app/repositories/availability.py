"""Load what the availability engine needs from the database, then run it."""

from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.orm import Session, selectinload

from app.availability.engine import (
    BayInfo,
    DayAvailability,
    DayHours,
    Occupied,
    Policy,
    ServiceInfo,
    find_slots,
)
from app.models import Bay, OpeningHours, Reservation, Service
from app.repositories.catalogue import get_setting


class SettingsUnavailable(Exception):
    """A setting the engine needs is missing or invalid."""


def _int_setting(session: Session, key: str, minimum: int) -> int:
    value = get_setting(session, key)
    # bool is a subclass of int in Python, but `true` is not a number of minutes.
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise SettingsUnavailable(key)
    return value


def load_policy(session: Session) -> Policy:
    name = get_setting(session, "garage_timezone")
    if not isinstance(name, str):
        raise SettingsUnavailable("garage_timezone")
    try:
        zone = ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise SettingsUnavailable("garage_timezone") from error
    return Policy(
        zone=zone,
        grid_minutes=_int_setting(session, "slot_grid_minutes", 5),
        buffer_minutes=_int_setting(session, "bay_buffer_minutes", 0),
        cutoff_minutes=_int_setting(session, "booking_cutoff_minutes", 0),
    )


def load_booking_window_days(session: Session) -> int:
    return _int_setting(session, "booking_window_days", 0)


def find_active_services(session: Session, slugs: Sequence[str]) -> list[Service]:
    """Active services with these slugs, in `slugs` order. Unknown or inactive ones are absent."""
    statement = select(Service).where(Service.slug.in_(slugs), Service.active.is_(True))
    found = {service.slug: service for service in session.scalars(statement)}
    return [found[slug] for slug in slugs if slug in found]


def day_availability(
    session: Session,
    services: Sequence[Service],
    day: date,
    now: datetime,
    policy: Policy,
) -> DayAvailability:
    bays = session.scalars(select(Bay).where(Bay.active.is_(True)))

    row = session.scalars(
        select(OpeningHours)
        .options(selectinload(OpeningHours.breaks))
        .where(OpeningHours.weekday == day.weekday())
    ).one_or_none()
    hours = None
    if row is not None and row.open_time is not None and row.close_time is not None:
        breaks = tuple((b.start_time, b.end_time) for b in row.breaks)
        hours = DayHours(open=row.open_time, close=row.close_time, breaks=breaks)

    # The whole local day, as a UTC range, so a 23- or 25-hour day is covered exactly.
    day_start = datetime.combine(day, time(0), tzinfo=policy.zone).astimezone(UTC)
    day_end = datetime.combine(day + timedelta(days=1), time(0), tzinfo=policy.zone).astimezone(UTC)
    reservations = session.scalars(
        select(Reservation).where(
            Reservation.active.is_(True),
            Reservation.during.overlaps(Range(day_start, day_end)),
        )
    )
    occupied = [
        Occupied(bay_id=r.bay_id, start=r.during.lower, end=r.during.upper)
        for r in reservations
        if r.during.lower is not None and r.during.upper is not None
    ]

    return find_slots(
        day,
        [ServiceInfo(s.id, s.duration_minutes, s.required_bay_type_id) for s in services],
        [BayInfo(b.id, b.bay_type_id) for b in bays],
        hours,
        occupied,
        policy,
        now,
    )
