"""The bookings in the way of a settings change: a bay taken out of use, or new hours.

A booking counts while it holds its time: held (and not past its hold), waiting for
approval, confirmed or in progress. Cancelled, expired, completed and no-show ones don't.
"""

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any, Final
from zoneinfo import ZoneInfo

from sqlalchemy import Select, select
from sqlalchemy.orm import Session, selectinload

from app.models import Booking, Reservation
from app.repositories.bookings import expired_hold
from app.repositories.hours import WeekdayHours
from app.schedule.view import local_midnight

COUNTING_STATUSES: Final = ("held", "pending_approval", "confirmed", "in_progress")


def fits(hours: WeekdayHours, start: datetime, end: datetime) -> bool:
    """Whether a job from `start` to `end` (garage-local) fits the day's hours: open that
    day, not before opening or after closing, and clear of every break. The bay buffer
    isn't part of it: it separates jobs, not a job and closing time."""
    if hours.open is None or hours.close is None or end.date() != start.date():
        return False
    begins, ends = start.time(), end.time()
    if begins < hours.open or ends > hours.close:
        return False
    return all(
        ends <= break_start or begins >= break_end for break_start, break_end in hours.breaks
    )


def _counting(now: datetime) -> Select[Booking]:
    return (
        select(Booking)
        .join(Reservation, Booking.reservation_id == Reservation.id)
        .options(selectinload(Booking.reservation).selectinload(Reservation.bay))
        .where(Booking.status.in_(COUNTING_STATUSES), ~expired_hold(now))
        .order_by(Booking.start_at, Booking.id)
    )


def bookings_in_bay(session: Session, bay_id: int, now: datetime) -> list[Booking]:
    """Counting bookings in the bay that haven't ended yet."""
    statement = _counting(now).where(Reservation.bay_id == bay_id, Booking.end_at > now)
    return list(session.scalars(statement))


def bookings_outside(
    session: Session,
    first: date,
    last: date | None,
    week: Mapping[int, WeekdayHours],
    zone: ZoneInfo,
    now: datetime,
) -> list[Booking]:
    """Counting bookings starting (garage-local) on a date in [first, last), or from `first`
    on when `last` is None, that `week` wouldn't allow on their weekday."""
    statement = _counting(now).where(Booking.start_at >= local_midnight(first, zone))
    if last is not None:
        statement = statement.where(Booking.start_at < local_midnight(last, zone))
    outside = []
    for booking in session.scalars(statement):
        start, end = booking.start_at.astimezone(zone), booking.end_at.astimezone(zone)
        if not fits(week[start.weekday()], start, end):
            outside.append(booking)
    return outside


@dataclass(frozen=True)
class Clash:
    reference: str
    start: str  # garage-local ISO
    bay: str
    held: bool  # being paid for right now: it clears by itself in a few minutes


def clash_body(bookings: Sequence[Booking], zone: ZoneInfo) -> dict[str, Any]:
    """The 409 body listing the bookings in the way, earliest first."""
    clashes = [
        Clash(
            reference=b.reference,
            start=b.start_at.astimezone(zone).isoformat(),  # "+00:00", never "Z"
            bay=b.reservation.bay.name,
            held=b.status == "held",
        )
        for b in sorted(bookings, key=lambda b: (b.start_at, b.id))
    ]
    return {"detail": "clashes", "bookings": [asdict(c) for c in clashes]}
