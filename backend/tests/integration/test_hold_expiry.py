"""Releasing expired holds, and availability ignoring them even before they're released."""

from datetime import UTC, date, datetime, timedelta

import pytest
from factories import make_hold
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Booking, EmailLog, Service
from app.repositories.availability import day_availability, load_hold_minutes, load_policy
from app.repositories.bookings import release_expired_holds, release_hold
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


def queued(session: Session) -> list[tuple[int, str]]:
    rows = session.scalars(select(EmailLog).order_by(EmailLog.id))
    return [(row.booking_id or 0, row.template) for row in rows]


def test_overdue_request_frees_slot_before_worker(seeded: Session) -> None:
    make_hold(seeded, MOT_0800, NOW - timedelta(seconds=1), status="pending_approval")
    assert MOT_0800 in mot_starts(seeded)


def test_live_request_and_approval_keep_their_slots(seeded: Session) -> None:
    make_hold(seeded, MOT_0800, NOW + timedelta(hours=1), status="pending_approval")
    make_hold(
        seeded, MOT_0800 + timedelta(hours=2), NOW + timedelta(hours=1), status="awaiting_deposit"
    )
    starts = mot_starts(seeded)
    assert MOT_0800 not in starts
    assert MOT_0800 + timedelta(hours=2) not in starts


def test_release_queues_one_email_per_request(seeded: Session) -> None:
    gone = NOW - timedelta(minutes=1)
    request = make_hold(seeded, MOT_0800, gone, status="pending_approval")
    approval = make_hold(seeded, MOT_0800 + timedelta(hours=2), gone, status="awaiting_deposit")
    make_hold(seeded, MOT_0800 + timedelta(hours=4), gone)  # a plain hold: no email

    assert release_expired_holds(seeded, NOW) == 3
    assert queued(seeded) == [(request.id, "request_expired"), (approval.id, "deposit_expired")]
    assert reload(seeded, request).status == "expired"
    assert not reload(seeded, approval).reservation.active

    assert release_expired_holds(seeded, NOW) == 0
    assert len(queued(seeded)) == 2


def test_release_hold_of_one_request_queues_its_email(seeded: Session) -> None:
    request = make_hold(seeded, MOT_0800, NOW - timedelta(minutes=1), status="pending_approval")
    release_hold(seeded, request)
    assert queued(seeded) == [(request.id, "request_expired")]
    assert request.status == "expired"


def test_release_hold_of_a_plain_hold_queues_nothing(seeded: Session) -> None:
    hold = make_hold(seeded, MOT_0800, NOW - timedelta(minutes=1), details=True)
    release_hold(seeded, hold)
    assert queued(seeded) == []
