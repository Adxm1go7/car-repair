"""The deposit for a booking staff approved: its form keeps the deadline, and a payment
confirms it, takes its time back, or is refunded."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from factories import make_deposit, make_hold
from fakes import FakeProvider
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.bookings.service import open_deposit_form
from app.models import Booking, EmailLog, Payment
from app.payments.service import cancel_booking, complete_deposit
from app.repositories.bookings import release_expired_holds
from app.seed import seed

NOW = datetime(2026, 11, 9, 9, tzinfo=UTC)
START = datetime(2026, 11, 12, 8, tzinfo=UTC)
DEADLINE = NOW + timedelta(hours=24)
LONDON = ZoneInfo("Europe/London")
REF = "cs_fake_1"


@pytest.fixture
def seeded(db_session: Session) -> Session:
    seed(db_session)
    return db_session


@pytest.fixture
def provider() -> FakeProvider:
    return FakeProvider()


def approved(session: Session, deadline: datetime = DEADLINE) -> Booking:
    return make_hold(session, START, deadline, status="awaiting_deposit")


def reload(session: Session, booking: Booking) -> Booking:
    session.expire_all()
    fresh = session.get(Booking, booking.id)
    assert fresh is not None
    return fresh


def refunds(session: Session) -> list[Payment]:
    return list(session.scalars(select(Payment).where(Payment.kind == "refund")))


def test_opening_form_keeps_payment_deadline(seeded: Session, provider: FakeProvider) -> None:
    booking = approved(seeded)
    first = open_deposit_form(seeded, provider, booking, NOW, amount_pence=2000, zone=LONDON)
    assert reload(seeded, booking).hold_expires_at == DEADLINE
    assert first.expires_in_seconds == 24 * 3600
    later = NOW + timedelta(minutes=5)
    second = open_deposit_form(seeded, provider, booking, later, amount_pence=2000, zone=LONDON)
    assert second.client_secret == first.client_secret
    assert second.expires_in_seconds == 24 * 3600 - 300
    assert len(provider.called("start_checkout")) == 1
    assert reload(seeded, booking).hold_expires_at == DEADLINE


def test_awaiting_deposit_payment_confirms(seeded: Session, provider: FakeProvider) -> None:
    booking = approved(seeded)
    make_deposit(seeded, booking, ref=REF)
    provider.mark_paid(REF)
    assert complete_deposit(seeded, provider, REF, NOW) is not None
    booking = reload(seeded, booking)
    assert (booking.status, booking.deposit_status) == ("confirmed", "paid")


def test_late_payment_on_expired_approval_with_time_free_confirms(
    seeded: Session, provider: FakeProvider
) -> None:
    booking = approved(seeded, deadline=NOW - timedelta(minutes=1))
    make_deposit(seeded, booking, ref=REF)
    provider.mark_paid(REF)
    assert complete_deposit(seeded, provider, REF, NOW) is not None
    assert reload(seeded, booking).status == "confirmed"
    assert refunds(seeded) == []


def test_late_payment_on_expired_approval_with_time_taken_refunds(
    seeded: Session, provider: FakeProvider
) -> None:
    booking = approved(seeded, deadline=NOW - timedelta(minutes=1))
    make_deposit(seeded, booking, ref=REF)
    complete_deposit(seeded, provider, REF, NOW)  # unpaid: nothing happens
    booking.status = "expired"
    booking.reservation.active = False
    seeded.flush()
    make_hold(seeded, START, NOW + timedelta(minutes=5))  # someone else takes the time
    provider.mark_paid(REF)
    assert complete_deposit(seeded, provider, REF, NOW) is None
    assert reload(seeded, booking).status == "expired"
    assert len(refunds(seeded)) == 1


def test_payment_on_cancelled_request_is_refunded(seeded: Session, provider: FakeProvider) -> None:
    booking = approved(seeded)
    make_deposit(seeded, booking, ref=REF)
    cancel_booking(seeded, provider, booking, NOW, by="customer", free_cancellation_hours=24)
    provider.mark_paid(REF)
    assert complete_deposit(seeded, provider, REF, NOW) is None
    booking = reload(seeded, booking)
    assert booking.status == "cancelled"
    assert booking.deposit_status == "refund_pending"  # the fake's refunds start pending
    assert len(refunds(seeded)) == 1


def expiry_emails(session: Session) -> list[EmailLog]:
    session.expire_all()
    return list(session.scalars(select(EmailLog).where(EmailLog.template == "deposit_expired")))


def late_paid_after_time_taken(session: Session, provider: FakeProvider) -> Booking:
    """An approval that ran out and was released (queuing its email), its time taken by
    someone else, and then paid on the form still open."""
    booking = approved(session, deadline=NOW - timedelta(minutes=1))
    make_deposit(session, booking, ref=REF)
    release_expired_holds(session, NOW)
    make_hold(session, START, NOW + timedelta(minutes=5))
    provider.mark_paid(REF)
    assert complete_deposit(session, provider, REF, NOW) is None
    return booking


def test_late_refund_on_an_approval_is_told_in_the_queued_email(
    seeded: Session, provider: FakeProvider
) -> None:
    late_paid_after_time_taken(seeded, provider)
    # The "time released" email hasn't gone yet: it goes once, and says about the refund.
    [email] = expiry_emails(seeded)
    assert email.status == "queued"


def test_late_refund_after_the_email_went_sends_another(
    seeded: Session, provider: FakeProvider
) -> None:
    booking = approved(seeded, deadline=NOW - timedelta(minutes=1))
    make_deposit(seeded, booking, ref=REF)
    release_expired_holds(seeded, NOW)
    for email in expiry_emails(seeded):
        email.status = "sent"
    seeded.flush()
    make_hold(seeded, START, NOW + timedelta(minutes=5))
    provider.mark_paid(REF)
    complete_deposit(seeded, provider, REF, NOW)
    assert [e.status for e in expiry_emails(seeded)] == ["sent", "queued"]


def test_late_refund_on_a_plain_hold_sends_no_expiry_email(
    seeded: Session, provider: FakeProvider
) -> None:
    hold = make_hold(seeded, START, NOW - timedelta(minutes=1), status="expired", details=True)
    make_deposit(seeded, hold, ref=REF)
    make_hold(seeded, START, NOW + timedelta(minutes=5))
    provider.mark_paid(REF)
    complete_deposit(seeded, provider, REF, NOW)
    assert expiry_emails(seeded) == []
