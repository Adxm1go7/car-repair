"""The database refuses email rows and booking links that break the rules."""

from datetime import UTC, datetime, timedelta

import pytest
from factories import make_hold
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Booking, BookingLink, EmailLog
from app.repositories.availability import load_reminder_hours_before
from app.seed import seed

START = datetime(2026, 11, 20, 9, tzinfo=UTC)


def confirmed(session: Session, start: datetime = START) -> Booking:
    return make_hold(session, start, start - timedelta(days=5), status="confirmed")


@pytest.fixture
def booking(db_session: Session) -> Booking:
    seed(db_session)
    return confirmed(db_session)


def email(booking: Booking, **changes: object) -> EmailLog:
    """A reminder for `booking` unless `changes` says otherwise."""
    values: dict[str, object] = {
        "template": "reminder",
        "booking_id": booking.id,
        "recipient": "sam@example.com",
        **changes,
    }
    return EmailLog(**values)


@pytest.mark.parametrize(
    "template",
    [
        "request_received",
        "approved",
        "proposed",
        "declined",
        "request_expired",
        "deposit_expired",
    ],
)
def test_approval_templates_are_allowed(
    db_session: Session, booking: Booking, template: str
) -> None:
    db_session.add(email(booking, template=template))
    db_session.flush()


def test_second_reminder_for_a_booking_is_rejected(db_session: Session, booking: Booking) -> None:
    db_session.add(email(booking))
    db_session.flush()
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.add(email(booking))
        db_session.flush()


def test_reminders_for_different_bookings_are_allowed(
    db_session: Session, booking: Booking
) -> None:
    other = confirmed(db_session, START + timedelta(days=1))
    db_session.add_all([email(booking), email(other)])
    db_session.flush()


def test_reminder_and_confirmation_for_one_booking_coexist(
    db_session: Session, booking: Booking
) -> None:
    db_session.add_all([email(booking), email(booking, template="confirmation")])
    db_session.flush()


def test_new_row_is_queued_and_due_now(db_session: Session, booking: Booking) -> None:
    row = email(booking, template="confirmation")
    db_session.add(row)
    db_session.flush()
    db_session.refresh(row)
    assert (row.status, row.attempts) == ("queued", 0)
    assert row.next_attempt_at is not None


@pytest.mark.parametrize(
    "changes",
    [{"template": "reschedule"}, {"status": "lost"}, {"attempts": -1}],
    ids=["unknown template", "unknown status", "negative attempts"],
)
def test_invalid_email_row_is_rejected(
    db_session: Session, booking: Booking, changes: dict[str, object]
) -> None:
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.add(email(booking, **{"template": "confirmation", **changes}))
        db_session.flush()


def test_link_token_hash_is_unique(db_session: Session, booking: Booking) -> None:
    expires = START + timedelta(days=7)
    db_session.add(BookingLink(booking_id=booking.id, token_hash="a" * 64, expires_at=expires))
    db_session.flush()
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.add(BookingLink(booking_id=booking.id, token_hash="a" * 64, expires_at=expires))
        db_session.flush()


def test_seed_adds_reminder_hours_before(db_session: Session, booking: Booking) -> None:
    assert load_reminder_hours_before(db_session) == 48
