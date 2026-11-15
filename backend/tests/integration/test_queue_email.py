"""A confirmed booking always has exactly one confirmation email queued, in the same transaction."""

from datetime import UTC, datetime, timedelta

import pytest
from factories import make_deposit, make_hold
from fakes import FakeProvider
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.email.queue import queue_email
from app.models import Booking, EmailLog
from app.payments.service import complete_deposit
from app.seed import seed

NOW = datetime(2026, 11, 9, 9, tzinfo=UTC)
START = datetime(2026, 11, 10, 8, tzinfo=UTC)
REF = "cs_fake_1"


@pytest.fixture
def seeded(db_session: Session) -> Session:
    seed(db_session)
    return db_session


@pytest.fixture
def provider() -> FakeProvider:
    return FakeProvider()


def emails(session: Session) -> list[EmailLog]:
    session.expire_all()
    return list(session.scalars(select(EmailLog).order_by(EmailLog.id)))


def held_and_paid(session: Session, provider: FakeProvider) -> Booking:
    booking = make_hold(session, START, NOW + timedelta(minutes=10), details=True)
    make_deposit(session, booking, ref=REF)
    provider.mark_paid(REF)
    return booking


def test_paying_a_held_booking_queues_one_confirmation(
    seeded: Session, provider: FakeProvider
) -> None:
    booking = held_and_paid(seeded, provider)
    complete_deposit(seeded, provider, REF, NOW)
    (email,) = emails(seeded)
    assert (email.template, email.status, email.attempts) == ("confirmation", "queued", 0)
    assert (email.booking_id, email.recipient) == (booking.id, "sam@example.com")
    assert email.next_attempt_at is not None


def test_late_payment_that_gets_its_time_back_queues_one_confirmation(
    seeded: Session, provider: FakeProvider
) -> None:
    booking = make_hold(seeded, START, NOW - timedelta(minutes=1), status="expired", details=True)
    make_deposit(seeded, booking, ref=REF)
    provider.mark_paid(REF)
    complete_deposit(seeded, provider, REF, NOW)
    assert [(e.template, e.booking_id) for e in emails(seeded)] == [("confirmation", booking.id)]


def test_late_payment_refunded_queues_nothing(seeded: Session, provider: FakeProvider) -> None:
    late = make_hold(seeded, START, NOW - timedelta(minutes=1), status="expired", details=True)
    make_deposit(seeded, late, ref=REF)
    make_hold(seeded, START, NOW + timedelta(minutes=5))  # someone else has the time now
    provider.mark_paid(REF)
    complete_deposit(seeded, provider, REF, NOW)
    assert emails(seeded) == []


def test_completing_twice_queues_once(seeded: Session, provider: FakeProvider) -> None:
    held_and_paid(seeded, provider)
    complete_deposit(seeded, provider, REF, NOW)
    complete_deposit(seeded, provider, REF, NOW + timedelta(minutes=1))
    assert len(emails(seeded)) == 1


def test_rolled_back_confirm_leaves_no_email(seeded: Session, provider: FakeProvider) -> None:
    held_and_paid(seeded, provider)
    nested = seeded.begin_nested()
    complete_deposit(seeded, provider, REF, NOW)
    nested.rollback()
    assert emails(seeded) == []


def test_queue_email_needs_a_recipient(seeded: Session) -> None:
    booking = make_hold(seeded, START, NOW + timedelta(minutes=10))  # no customer details yet
    with pytest.raises(ValueError, match="email"):
        queue_email(seeded, "confirmation", booking)
