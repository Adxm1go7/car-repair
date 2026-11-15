"""Reminders: one per confirmed booking, queued once it's within 48 hours of its start."""

from datetime import UTC, datetime, timedelta

import pytest
from factories import make_hold
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.email.reminders import queue_due_reminders
from app.models import Booking, EmailLog
from app.seed import seed

START = datetime(2026, 11, 20, 9, tzinfo=UTC)
HOURS = 48


@pytest.fixture
def seeded(db_session: Session) -> Session:
    seed(db_session)
    return db_session


def confirmed(
    session: Session,
    *,
    confirmed_at: datetime = START - timedelta(days=5),
    status: str = "confirmed",
) -> Booking:
    booking = make_hold(session, START, START - timedelta(days=6), status="confirmed")
    booking.confirmed_at = confirmed_at
    booking.status = status
    session.flush()
    return booking


def reminders(session: Session) -> list[EmailLog]:
    return list(session.scalars(select(EmailLog).where(EmailLog.template == "reminder")))


def test_queued_once_inside_the_window(seeded: Session) -> None:
    booking = confirmed(seeded)
    now = START - timedelta(hours=47)
    assert queue_due_reminders(seeded, now, HOURS) == 1
    assert queue_due_reminders(seeded, now + timedelta(minutes=1), HOURS) == 0
    (reminder,) = reminders(seeded)
    assert (reminder.booking_id, reminder.status) == (booking.id, "queued")
    assert reminder.recipient == "sam@example.com"


def test_window_opens_exactly_48_hours_before(seeded: Session) -> None:
    confirmed(seeded)
    assert queue_due_reminders(seeded, START - timedelta(hours=HOURS), HOURS) == 1


def test_not_yet(seeded: Session) -> None:
    confirmed(seeded)
    assert queue_due_reminders(seeded, START - timedelta(hours=49), HOURS) == 0
    assert reminders(seeded) == []


def test_booked_inside_48_hours_gets_none(seeded: Session) -> None:
    confirmed(seeded, confirmed_at=START - timedelta(hours=30))
    assert queue_due_reminders(seeded, START - timedelta(hours=29), HOURS) == 0
    assert reminders(seeded) == []


def test_cancelled_gets_none(seeded: Session) -> None:
    confirmed(seeded, status="cancelled")
    assert queue_due_reminders(seeded, START - timedelta(hours=47), HOURS) == 0
    assert reminders(seeded) == []


def test_after_start_gets_none(seeded: Session) -> None:
    confirmed(seeded)
    assert queue_due_reminders(seeded, START, HOURS) == 0
    assert queue_due_reminders(seeded, START + timedelta(hours=1), HOURS) == 0
    assert reminders(seeded) == []
