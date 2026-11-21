"""The demo site keeps each email in demo_inbox instead of sending it."""

from datetime import UTC, datetime, timedelta

import pytest
from factories import make_deposit, make_hold
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import AppConfig
from app.email.message import OutgoingEmail
from app.email.outbox import send_due_emails
from app.email.queue import queue_email
from app.email.sender import DemoInboxSender, EmailUnavailable, SmtpSender
from app.models import DemoInboxEmail, EmailLog
from app.seed import seed
from app.worker import make_sender

NOW = datetime(2026, 11, 9, 9, tzinfo=UTC)
START = datetime(2026, 11, 20, 9, tzinfo=UTC)
BASE_URL = "https://demo.test"


@pytest.fixture
def queued_confirmation(db_session: Session) -> int:
    """A confirmed booking with its confirmation email due at NOW. Returns the email's id."""
    seed(db_session)
    booking = make_hold(db_session, START, NOW + timedelta(minutes=10), status="confirmed")
    make_deposit(db_session, booking, ref=f"cs_{booking.reference}", status="paid")
    email = queue_email(db_session, "confirmation", booking)
    assert email is not None
    email.next_attempt_at = NOW
    db_session.commit()
    return email.id


def inbox(session: Session) -> list[DemoInboxEmail]:
    session.expire_all()
    return list(session.scalars(select(DemoInboxEmail)))


def test_demo_sender_stores_the_email(db_session: Session, queued_confirmation: int) -> None:
    sent = send_due_emails(db_session, DemoInboxSender(db_session), NOW, BASE_URL)

    assert sent == 1
    [stored] = inbox(db_session)
    log = db_session.get(EmailLog, queued_confirmation)
    assert log is not None
    assert log.status == "sent"
    assert stored.template == "confirmation"
    assert stored.recipient == log.recipient
    assert stored.subject.startswith("Your booking is confirmed")
    assert f"{BASE_URL}/booking/" in stored.text
    assert stored.html.startswith("<")


class StoresThenFails(DemoInboxSender):
    def send(self, message: OutgoingEmail) -> None:
        super().send(message)
        raise EmailUnavailable("told to fail after storing")


def test_inbox_row_rolls_back_with_failure(db_session: Session, queued_confirmation: int) -> None:
    send_due_emails(db_session, StoresThenFails(db_session), NOW, BASE_URL)

    assert db_session.scalar(select(func.count()).select_from(DemoInboxEmail)) == 0
    log = db_session.get(EmailLog, queued_confirmation)
    assert log is not None
    assert (log.status, log.attempts) == ("queued", 1)


def test_worker_uses_smtp_when_off(db_session: Session) -> None:
    config = AppConfig(database_url="x")
    assert isinstance(make_sender(config, db_session), SmtpSender)


def test_worker_uses_inbox_when_on(db_session: Session) -> None:
    config = AppConfig(database_url="x", demo_site=True)
    assert isinstance(make_sender(config, db_session), DemoInboxSender)
