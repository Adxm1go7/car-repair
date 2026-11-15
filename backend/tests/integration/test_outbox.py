"""The worker's outbox: sends due emails one at a time, retries with backoff, skips stale ones."""

import re
from datetime import UTC, datetime, timedelta

import pytest
from factories import make_deposit, make_hold
from fakes import FakeSender
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.bookings.links import find_linked_booking
from app.email.message import EmailTemplate
from app.email.outbox import MAX_ATTEMPTS, send_due_emails
from app.email.queue import queue_email
from app.models import Booking, BookingLink, EmailLog
from app.seed import seed

NOW = datetime(2026, 11, 9, 9, tzinfo=UTC)
START = datetime(2026, 11, 20, 9, tzinfo=UTC)
BASE_URL = "http://localhost:8080"


@pytest.fixture
def seeded(db_session: Session) -> Session:
    seed(db_session)
    return db_session


@pytest.fixture
def sender() -> FakeSender:
    return FakeSender()


def confirmed(session: Session, start: datetime = START, email: str | None = None) -> Booking:
    booking = make_hold(session, start, NOW + timedelta(minutes=10), status="confirmed")
    if email is not None:
        booking.customer_email = email
    make_deposit(session, booking, ref=f"cs_{booking.reference}", status="paid")
    return booking


def queued(session: Session, booking: Booking, template: EmailTemplate = "confirmation") -> int:
    """Queue an email, due at NOW (the column's default is the database's real clock)."""
    email = queue_email(session, template, booking)
    email.next_attempt_at = NOW
    session.commit()
    return email.id


def row(session: Session, email_id: int) -> EmailLog:
    session.expire_all()
    found = session.get(EmailLog, email_id)
    assert found is not None
    return found


def links(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(BookingLink)) or 0


def test_sends_and_marks_sent(seeded: Session, sender: FakeSender) -> None:
    email_id = queued(seeded, confirmed(seeded))
    assert send_due_emails(seeded, sender, NOW, BASE_URL) == 1
    (message,) = sender.sent
    assert message.to == "sam@example.com"
    email = row(seeded, email_id)
    assert (email.status, email.sent_at, email.attempts) == ("sent", NOW, 0)
    assert links(seeded) == 1


def test_sent_link_opens_the_booking(seeded: Session, sender: FakeSender) -> None:
    booking = confirmed(seeded)
    queued(seeded, booking)
    send_due_emails(seeded, sender, NOW, BASE_URL)
    match = re.search(rf"{BASE_URL}/booking/{booking.reference}#t=([\w-]+)", sender.sent[0].text)
    assert match is not None
    found = find_linked_booking(seeded, booking.reference, match.group(1), NOW)
    assert found is not None
    assert found.id == booking.id


def test_not_due_yet_is_left(seeded: Session, sender: FakeSender) -> None:
    email_id = queued(seeded, confirmed(seeded))
    row(seeded, email_id).next_attempt_at = NOW + timedelta(minutes=1)
    seeded.commit()
    assert send_due_emails(seeded, sender, NOW, BASE_URL) == 0
    assert sender.sent == []
    assert row(seeded, email_id).status == "queued"


def test_failure_backs_off_then_fails(seeded: Session, sender: FakeSender) -> None:
    email_id = queued(seeded, confirmed(seeded))
    sender.fail = True

    assert send_due_emails(seeded, sender, NOW, BASE_URL) == 0
    email = row(seeded, email_id)
    assert (email.status, email.attempts) == ("queued", 1)
    assert email.next_attempt_at == NOW + timedelta(minutes=1)
    assert email.last_error is not None
    assert links(seeded) == 0  # the link made for the failed send was rolled back

    for _ in range(MAX_ATTEMPTS - 1):
        send_due_emails(seeded, sender, row(seeded, email_id).next_attempt_at, BASE_URL)
    email = row(seeded, email_id)
    assert (email.status, email.attempts) == ("failed", MAX_ATTEMPTS)
    assert sender.sent == []


def test_one_failure_does_not_block_the_batch(seeded: Session, sender: FakeSender) -> None:
    first = queued(seeded, confirmed(seeded, email="first@example.com"))
    second = queued(seeded, confirmed(seeded, START + timedelta(hours=3), "second@example.com"))
    sender.fail_for = {"first@example.com"}
    assert send_due_emails(seeded, sender, NOW, BASE_URL) == 1
    assert [m.to for m in sender.sent] == ["second@example.com"]
    assert (row(seeded, first).status, row(seeded, first).attempts) == ("queued", 1)
    assert row(seeded, second).status == "sent"


def test_cancelled_booking_confirmation_is_skipped(seeded: Session, sender: FakeSender) -> None:
    booking = confirmed(seeded)
    email_id = queued(seeded, booking)
    booking.status = "cancelled"
    seeded.commit()
    assert send_due_emails(seeded, sender, NOW, BASE_URL) == 0
    assert sender.sent == []
    assert row(seeded, email_id).status == "skipped"


def test_cancellation_email_has_no_link(seeded: Session, sender: FakeSender) -> None:
    booking = confirmed(seeded)
    booking.status = "cancelled"
    email_id = queued(seeded, booking, "cancellation")
    assert send_due_emails(seeded, sender, NOW, BASE_URL) == 1
    (message,) = sender.sent
    assert "#t=" not in message.text
    assert "#t=" not in message.html
    assert row(seeded, email_id).status == "sent"
    assert links(seeded) == 0
