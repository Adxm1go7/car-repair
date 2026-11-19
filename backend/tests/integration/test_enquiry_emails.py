"""The worker sends enquiry emails: a "received" one always, a "declined" one while declined."""

from datetime import UTC, datetime

import pytest
from factories import make_enquiry, make_staff
from fakes import FakeSender
from sqlalchemy.orm import Session

from app.email.message import EnquiryTemplate
from app.email.outbox import send_due_emails
from app.email.queue import queue_enquiry_email
from app.models import EmailLog, Enquiry
from app.seed import seed

NOW = datetime(2026, 11, 19, 9, tzinfo=UTC)
BASE_URL = "http://localhost:8080"


@pytest.fixture
def seeded(db_session: Session) -> Session:
    seed(db_session)
    return db_session


def queued(
    session: Session,
    enquiry: Enquiry,
    template: EnquiryTemplate,
    context: dict[str, object] | None = None,
) -> EmailLog:
    email = queue_enquiry_email(session, template, enquiry, context)
    email.next_attempt_at = NOW
    session.commit()
    return email


def test_queue_enquiry_email(seeded: Session) -> None:
    enquiry = make_enquiry(seeded)
    email = queue_enquiry_email(seeded, "enquiry_received", enquiry)
    assert (email.enquiry_id, email.booking_id, email.staff_user_id) == (enquiry.id, None, None)
    assert email.recipient == "sam@example.com"
    assert email.status == "queued"


def test_outbox_sends_enquiry_emails(seeded: Session) -> None:
    enquiry = make_enquiry(seeded, status="declined", created_at=NOW, reason="Too busy")
    received = queued(seeded, enquiry, "enquiry_received")
    declined = queued(seeded, enquiry, "enquiry_declined", {"reason": "Too busy"})
    sender = FakeSender()
    assert send_due_emails(seeded, sender, NOW, BASE_URL) == 2
    assert [m.subject for m in sender.sent] == [
        "We've got your enquiry",
        "We can't take on your enquiry",
    ]
    assert all(m.to == "sam@example.com" for m in sender.sent)
    assert "Reason: Too busy" in sender.sent[1].text
    assert "Rattle from the front left" in sender.sent[0].text
    seeded.refresh(received)
    seeded.refresh(declined)
    assert (received.status, declined.status) == ("sent", "sent")


def test_outbox_sends_received_after_decline(seeded: Session) -> None:
    staff_id = make_staff(seeded).id
    enquiry = make_enquiry(seeded)
    received = queued(seeded, enquiry, "enquiry_received")
    enquiry.status = "declined"
    enquiry.handled_at = NOW
    enquiry.handled_by = staff_id
    seeded.commit()
    sender = FakeSender()
    assert send_due_emails(seeded, sender, NOW, BASE_URL) == 1
    seeded.refresh(received)
    assert received.status == "sent"


def test_declined_email_skipped_unless_declined(seeded: Session) -> None:
    enquiry = make_enquiry(seeded)
    email = queued(seeded, enquiry, "enquiry_declined")
    assert send_due_emails(seeded, FakeSender(), NOW, BASE_URL) == 0
    seeded.refresh(email)
    assert email.status == "skipped"
