"""Admins' changes to opening hours: add a timetable from a date, edit or delete a future one.

Each takes the hours-and-bays lock exclusive, then checks the bookings in the dates it
affects, `[starts_on, next starts_on)`, against the hours that would apply there: the new or
edited week, or for a delete the week before it, which carries on over those dates. A
clash refuses the change with nothing saved. Nothing here commits.
"""

from collections.abc import Mapping
from datetime import date, datetime, time
from typing import Any, Literal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Booking, OpeningHours, OpeningHoursBreak, StaffUser, Timetable
from app.repositories.hours import WeekdayHours, week_of
from app.settings.clashes import bookings_outside
from app.settings.lock import lock_exclusive
from app.staff.audit import record_audit

Week = Mapping[int, WeekdayHours]  # weekday 0–6 → hours
State = Literal["past", "current", "future"]


class StartTooSoon(Exception):
    """New hours can start tomorrow at the earliest, so nobody's open booking page changes."""


class DateTaken(Exception):
    pass


class NotAllowed(Exception):
    """The timetable is in force today or was in the past: it's fixed."""


class HoursClash(Exception):
    """The bookings the change would leave outside the hours."""

    def __init__(self, bookings: list[Booking]) -> None:
        super().__init__("clashes")
        self.bookings = bookings


def list_timetables(session: Session) -> list[Timetable]:
    """Every timetable with its days and breaks, oldest first."""
    statement = (
        select(Timetable)
        .options(selectinload(Timetable.days).selectinload(OpeningHours.breaks))
        .order_by(Timetable.starts_on)
    )
    return list(session.scalars(statement))


def states(timetables: list[Timetable], today: date) -> dict[int, State]:
    """Each timetable (oldest first) as past, current (in force today) or future."""
    result: dict[int, State] = {}
    for index, timetable in enumerate(timetables):
        following = timetables[index + 1].starts_on if index + 1 < len(timetables) else None
        if timetable.starts_on > today:
            result[timetable.id] = "future"
        elif following is not None and following <= today:
            result[timetable.id] = "past"
        else:
            result[timetable.id] = "current"
    return result


def _hhmm(value: time | None) -> str | None:
    return value.strftime("%H:%M") if value is not None else None


def snapshot(starts_on: date, week: Week) -> dict[str, Any]:
    """The whole week, for the audit log."""
    return {
        "starts_on": starts_on.isoformat(),
        "days": [
            {
                "weekday": weekday,
                "open": _hhmm(week[weekday].open),
                "close": _hhmm(week[weekday].close),
                "breaks": [
                    {"start": _hhmm(start), "end": _hhmm(end)}
                    for start, end in week[weekday].breaks
                ],
            }
            for weekday in range(7)
        ],
    }


def _next_start(session: Session, after: date) -> date | None:
    statement = select(Timetable.starts_on).where(Timetable.starts_on > after)
    return session.scalars(statement.order_by(Timetable.starts_on).limit(1)).first()


def _check(session: Session, first: date, week: Week, zone: ZoneInfo, now: datetime) -> None:
    clashes = bookings_outside(session, first, _next_start(session, first), week, zone, now)
    if clashes:
        raise HoursClash(clashes)


def _locked_future(session: Session, timetable_id: int, now: datetime, zone: ZoneInfo) -> Timetable:
    """After the lock: the timetable, if it's still there and still in the future."""
    timetable = session.get(Timetable, timetable_id, populate_existing=True)
    if timetable is None:
        raise LookupError(timetable_id)
    if timetable.starts_on <= now.astimezone(zone).date():
        raise NotAllowed
    return timetable


def _write_days(session: Session, timetable: Timetable, week: Week) -> None:
    """Make the timetable's rows say `week`: each weekday updated in place, breaks replaced."""
    rows = {row.weekday: row for row in timetable.days}
    for weekday in range(7):
        hours = week[weekday]
        row = rows.get(weekday)
        if row is None:
            row = OpeningHours(timetable_id=timetable.id, weekday=weekday)
            timetable.days.append(row)
        row.open_time, row.close_time = hours.open, hours.close
        row.breaks.clear()
    session.flush()  # the old breaks go before the new ones arrive
    for weekday in range(7):
        for start, end in week[weekday].breaks:
            session.add(
                OpeningHoursBreak(
                    timetable_id=timetable.id, weekday=weekday, start_time=start, end_time=end
                )
            )
    session.flush()
    session.expire(timetable, ["days"])


def create_timetable(
    session: Session, admin: StaffUser, starts_on: date, week: Week, zone: ZoneInfo, now: datetime
) -> Timetable:
    """New hours from `starts_on` (tomorrow at the earliest, not a date already used)."""
    if starts_on <= now.astimezone(zone).date():
        raise StartTooSoon
    lock_exclusive(session)
    if session.scalars(select(Timetable.id).where(Timetable.starts_on == starts_on)).first():
        raise DateTaken
    _check(session, starts_on, week, zone, now)
    timetable = Timetable(starts_on=starts_on, created_by=admin.id)
    session.add(timetable)
    session.flush()
    _write_days(session, timetable, week)
    record_audit(
        session,
        admin,
        "hours.create",
        "timetable",
        timetable.id,
        after=snapshot(starts_on, week),
        now=now,
    )
    return timetable


def replace_timetable(
    session: Session,
    admin: StaffUser,
    timetable_id: int,
    week: Week,
    zone: ZoneInfo,
    now: datetime,
) -> Timetable:
    """Replace a future timetable's days and breaks. Its start date never changes."""
    lock_exclusive(session)
    timetable = _locked_future(session, timetable_id, now, zone)
    _check(session, timetable.starts_on, week, zone, now)
    before = snapshot(timetable.starts_on, week_of(timetable))
    _write_days(session, timetable, week)
    record_audit(
        session,
        admin,
        "hours.update",
        "timetable",
        timetable.id,
        before=before,
        after=snapshot(timetable.starts_on, week),
        now=now,
    )
    return timetable


def delete_timetable(
    session: Session, admin: StaffUser, timetable_id: int, zone: ZoneInfo, now: datetime
) -> None:
    """Delete a future timetable. The one before it carries on over its dates, so those
    dates' bookings are checked against that one."""
    lock_exclusive(session)
    timetable = _locked_future(session, timetable_id, now, zone)
    previous = session.scalars(
        select(Timetable)
        .where(Timetable.starts_on < timetable.starts_on)
        .order_by(Timetable.starts_on.desc())
        .limit(1)
    ).one()  # there's always one: the first starts in 2000, and this one is in the future
    _check(session, timetable.starts_on, week_of(previous), zone, now)
    before = snapshot(timetable.starts_on, week_of(timetable))
    session.delete(timetable)
    session.flush()
    record_audit(session, admin, "hours.delete", "timetable", timetable_id, before=before, now=now)
