"""Which opening hours apply on a date: the timetable in force then, and its day."""

import bisect
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, time
from typing import Final

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import OpeningHours, Timetable


@dataclass(frozen=True)
class WeekdayHours:
    """One weekday's garage-local hours and breaks. Closed when `open` is None."""

    open: time | None
    close: time | None
    breaks: tuple[tuple[time, time], ...]


CLOSED: Final = WeekdayHours(None, None, ())


def _day_hours(row: OpeningHours) -> WeekdayHours:
    if row.open_time is None or row.close_time is None:
        return CLOSED
    breaks = tuple((b.start_time, b.end_time) for b in row.breaks)
    return WeekdayHours(row.open_time, row.close_time, breaks)


def week_of(timetable: Timetable) -> dict[int, WeekdayHours]:
    """Weekday 0–6 → hours. A weekday with no row is closed."""
    rows = {row.weekday: row for row in timetable.days}
    return {
        weekday: _day_hours(rows[weekday]) if weekday in rows else CLOSED for weekday in range(7)
    }


_WITH_DAYS: Final = selectinload(Timetable.days).selectinload(OpeningHours.breaks)


def timetable_on(session: Session, day: date) -> Timetable:
    """The timetable in force on `day`: the latest to start on or before it. There's always
    one, because the first starts in 2000."""
    return session.scalars(
        select(Timetable)
        .options(_WITH_DAYS)
        .where(Timetable.starts_on <= day)
        .order_by(Timetable.starts_on.desc())
        .limit(1)
    ).one()


def hours_on(session: Session, days: Sequence[date]) -> dict[date, WeekdayHours]:
    """Each day's hours, from the timetable in force on it. One query for all the days."""
    if not days:
        return {}
    first, last = min(days), max(days)
    # The timetable in force on the first day, and every one starting up to the last day.
    floor = (
        select(func.max(Timetable.starts_on)).where(Timetable.starts_on <= first).scalar_subquery()
    )
    timetables = list(
        session.scalars(
            select(Timetable)
            .options(_WITH_DAYS)
            .where(Timetable.starts_on >= func.coalesce(floor, first), Timetable.starts_on <= last)
            .order_by(Timetable.starts_on)
        )
    )
    starts = [t.starts_on for t in timetables]
    weeks = [week_of(t) for t in timetables]
    result = {}
    for day in days:
        index = bisect.bisect_right(starts, day) - 1
        result[day] = weeks[index][day.weekday()] if index >= 0 else CLOSED
    return result
