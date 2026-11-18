"""Which bookings stand in the way of taking a bay out of use, or of new opening hours."""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from factories import make_hold
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Bay
from app.repositories.hours import CLOSED, WeekdayHours
from app.seed import seed
from app.settings.clashes import bookings_in_bay, bookings_outside, clash_body

LONDON = ZoneInfo("Europe/London")
NOW = datetime(2026, 11, 9, 9, tzinfo=UTC)  # Monday
LATER = NOW + timedelta(days=30)


@pytest.fixture
def seeded(db_session: Session) -> Session:
    seed(db_session)
    return db_session


def mot_bay(session: Session) -> int:
    return session.scalars(select(Bay.id).where(Bay.slug == "mot-bay")).one()


def utc(day: int, hour: int) -> datetime:
    return datetime(2026, 11, day, hour, tzinfo=UTC)  # November: London is on GMT


def book(session: Session, start: datetime, status: str, expires: datetime = LATER) -> str:
    details = status != "held"
    return make_hold(session, start, expires, status=status, details=details).reference


def test_bookings_in_bay_counts_each_status(seeded: Session) -> None:
    counted = {
        book(seeded, utc(10, 9), "held"),
        book(seeded, utc(10, 11), "pending_approval"),
        book(seeded, utc(10, 13), "confirmed"),
        book(seeded, utc(10, 15), "in_progress"),
    }
    for hour, status in [(9, "cancelled"), (11, "expired"), (13, "completed"), (15, "no_show")]:
        book(seeded, utc(11, hour), status)
    found = bookings_in_bay(seeded, mot_bay(seeded), NOW)
    assert {b.reference for b in found} == counted


def test_bookings_in_bay_ignores_ones_already_over(seeded: Session) -> None:
    book(seeded, utc(9, 7), "confirmed")  # ended 08:00, before NOW (09:00)
    assert bookings_in_bay(seeded, mot_bay(seeded), NOW) == []


def test_expired_hold_does_not_count(seeded: Session) -> None:
    book(seeded, utc(10, 9), "held", expires=NOW - timedelta(minutes=1))
    assert bookings_in_bay(seeded, mot_bay(seeded), NOW) == []
    week = dict.fromkeys(range(7), CLOSED)
    assert bookings_outside(seeded, date(2026, 11, 10), None, week, LONDON, NOW) == []


def test_bookings_outside_finds_those_the_hours_leave_out(seeded: Session) -> None:
    early = book(seeded, utc(10, 8), "confirmed")  # Tue 08:00–09:00
    book(seeded, utc(10, 10), "confirmed")  # Tue 10:00–11:00
    # New Tuesday hours from 09:00: only the 08:00 booking falls outside.
    week = dict.fromkeys(range(7), CLOSED) | {1: WeekdayHours(time(9), time(17), ())}
    found = bookings_outside(seeded, date(2026, 11, 10), None, week, LONDON, NOW)
    assert [b.reference for b in found] == [early]


def test_bookings_outside_respects_range_end(seeded: Session) -> None:
    book(seeded, utc(10, 9), "confirmed")  # Tue 10 Nov
    on_17th = book(seeded, utc(17, 9), "confirmed")  # Tue 17 Nov
    closed = dict.fromkeys(range(7), CLOSED)
    found = bookings_outside(seeded, date(2026, 11, 11), date(2026, 11, 18), closed, LONDON, NOW)
    assert [b.reference for b in found] == [on_17th]
    # The range ends before the 17th: a later timetable takes over from then.
    assert (
        bookings_outside(seeded, date(2026, 11, 11), date(2026, 11, 17), closed, LONDON, NOW) == []
    )


def test_clash_body_shape(seeded: Session) -> None:
    held = make_hold(seeded, utc(10, 9), LATER)
    confirmed = make_hold(seeded, utc(10, 11), LATER, status="confirmed", bay_slug="bay-1")
    assert clash_body([confirmed, held], LONDON) == {
        "detail": "clashes",
        "bookings": [
            {
                "reference": held.reference,
                "start": "2026-11-10T09:00:00+00:00",
                "bay": "MOT bay",
                "held": True,
            },
            {
                "reference": confirmed.reference,
                "start": "2026-11-10T11:00:00+00:00",
                "bay": "Bay 1",
                "held": False,
            },
        ],
    }
