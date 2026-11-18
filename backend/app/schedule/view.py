"""Loading the schedule: the bays, each day's hours, and what occupies each bay."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.orm import Session, selectinload

from app.models import Bay, Block, Booking, OpeningHours, Reservation
from app.repositories.bookings import expired_hold


@dataclass(frozen=True)
class DayHours:
    day: date
    open: time | None
    close: time | None
    breaks: tuple[tuple[time, time], ...]


@dataclass(frozen=True)
class ScheduleItem:
    """A booking or a block in one bay. `booking` or `block` is set, never both."""

    bay_id: int
    start: datetime
    end: datetime
    booking: Booking | None
    block: Block | None


@dataclass(frozen=True)
class Schedule:
    bays: list[Bay]
    days: list[DayHours]
    items: list[ScheduleItem]


def local_midnight(day: date, zone: ZoneInfo) -> datetime:
    """The start of a local day, in UTC: a clock-change day is 23 or 25 hours long."""
    return datetime.combine(day, time(0), tzinfo=zone).astimezone(UTC)


def load_schedule(
    session: Session, first: date, days: int, zone: ZoneInfo, now: datetime
) -> Schedule:
    """Everything from local midnight on `first` for `days` days. Cancelled and expired
    bookings, holds past their time and removed blocks are left out."""
    bays = list(
        session.scalars(
            select(Bay)
            .options(selectinload(Bay.bay_type))
            .where(Bay.active.is_(True))
            .order_by(Bay.id)
        )
    )
    hours = {
        row.weekday: row
        for row in session.scalars(select(OpeningHours).options(selectinload(OpeningHours.breaks)))
    }
    day_list = [first + timedelta(days=n) for n in range(days)]
    day_hours = []
    for day in day_list:
        row = hours.get(day.weekday())
        day_hours.append(
            DayHours(
                day=day,
                open=row.open_time if row else None,
                close=row.close_time if row else None,
                breaks=tuple((b.start_time, b.end_time) for b in row.breaks) if row else (),
            )
        )

    start = local_midnight(first, zone)
    end = local_midnight(first + timedelta(days=days), zone)
    rows = session.execute(
        select(Reservation, Booking)
        .outerjoin(Booking, Booking.reservation_id == Reservation.id)
        .options(selectinload(Reservation.block), selectinload(Booking.items))
        .where(
            Reservation.active.is_(True),
            Reservation.during.overlaps(Range(start, end)),
            or_(Booking.id.is_(None), ~expired_hold(now)),
        )
        .order_by(Reservation.during, Reservation.bay_id)
    ).all()

    items = []
    for reservation, booking in rows:
        if booking is not None:
            items.append(
                ScheduleItem(reservation.bay_id, booking.start_at, booking.end_at, booking, None)
            )
        elif reservation.block is not None:
            during = reservation.during
            assert during.lower is not None and during.upper is not None  # noqa: S101 - bounded
            items.append(
                ScheduleItem(
                    reservation.bay_id, during.lower, during.upper, None, reservation.block
                )
            )
    return Schedule(bays=bays, days=day_hours, items=items)
