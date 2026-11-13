"""Releasing expired holds, and availability ignoring them even before they're released."""

from datetime import UTC, date, datetime, timedelta

import pytest
from factories import make_hold
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Booking, Service
from app.repositories.availability import day_availability, load_hold_minutes, load_policy
from app.repositories.bookings import release_expired_holds
from app.seed import seed

NOW = datetime(2026, 11, 9, 9, tzinfo=UTC)  # Monday 09:00 in London (GMT)
DAY = date(2026, 11, 10)
MOT_0800 = datetime(2026, 11, 10, 8, tzinfo=UTC)  # local time equals UTC in November


@pytest.fixture
def seeded(db_session: Session) -> Session:
    seed(db_session)
    return db_session


def mot_starts(session: Session) -> list[datetime]:
    mot = session.scalars(select(Service).where(Service.slug == "mot-test")).one()
    result = day_availability(session, [mot], DAY, NOW, load_policy(session))
    return [slot.start for slot in result.slots]


def reload(session: Session, booking: Booking) -> Booking:
    session.expire_all()
    fresh = session.get(Booking, booking.id)
    assert fresh is not None
    return fresh


def test_release_expired_holds_releases_only_expired_held(seeded: Session) -> None:
    expired = make_hold(seeded, MOT_0800, NOW - timedelta(minutes=1))
    live = make_hold(seeded, MOT_0800 + timedelta(hours=2), NOW + timedelta(minutes=5))
    confirmed = make_hold(
        seeded, MOT_0800 + timedelta(hours=4), NOW - timedelta(minutes=1), status="confirmed"
    )

    assert release_expired_holds(seeded, NOW) == 1

    expired, live, confirmed = (reload(seeded, b) for b in (expired, live, confirmed))
    assert (expired.status, expired.reservation.active) == ("expired", False)
    assert (live.status, live.reservation.active) == ("held", True)
    assert (confirmed.status, confirmed.reservation.active) == ("confirmed", True)


def test_release_with_nothing_expired_returns_zero(seeded: Session) -> None:
    make_hold(seeded, MOT_0800, NOW + timedelta(minutes=5))
    assert release_expired_holds(seeded, NOW) == 0


def test_availability_ignores_an_expired_hold_before_release(seeded: Session) -> None:
    hold = make_hold(seeded, MOT_0800, NOW - timedelta(seconds=1))
    assert MOT_0800 in mot_starts(seeded)
    assert reload(seeded, hold).reservation.active  # nothing has released it yet


def test_availability_respects_a_live_hold(seeded: Session) -> None:
    make_hold(seeded, MOT_0800, NOW + timedelta(minutes=5))
    assert MOT_0800 not in mot_starts(seeded)


def test_availability_respects_a_confirmed_booking_past_its_hold_time(seeded: Session) -> None:
    make_hold(seeded, MOT_0800, NOW - timedelta(minutes=5), status="confirmed")
    assert MOT_0800 not in mot_starts(seeded)


def test_load_hold_minutes_reads_the_setting(seeded: Session) -> None:
    assert load_hold_minutes(seeded) == 5
