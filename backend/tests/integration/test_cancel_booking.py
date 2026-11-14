"""cancel_booking frees the time and refunds when the rule says so. No route uses it yet."""

from datetime import UTC, datetime, timedelta
from typing import Literal

import pytest
from factories import make_deposit, make_hold
from fakes import FakeProvider
from sqlalchemy.orm import Session

from app.models import Booking
from app.payments.service import cancel_booking
from app.seed import seed

START = datetime(2026, 11, 20, 9, tzinfo=UTC)


@pytest.fixture
def paid(db_session: Session) -> Booking:
    seed(db_session)
    booking = make_hold(db_session, START, START - timedelta(days=5), status="confirmed")
    deposit = make_deposit(db_session, booking, status="paid")
    deposit.payment_intent_ref = "pi_1"
    db_session.flush()
    return booking


def cancel(
    session: Session, booking: Booking, now: datetime, by: Literal["customer", "garage"]
) -> FakeProvider:
    provider = FakeProvider()
    cancel_booking(session, provider, booking, now, by, 24)
    session.expire_all()
    return provider


def test_customer_in_time_is_refunded(db_session: Session, paid: Booking) -> None:
    provider = cancel(db_session, paid, START - timedelta(hours=25), "customer")
    assert len(provider.called("refund")) == 1
    assert (paid.status, paid.deposit_status) == ("cancelled", "refund_pending")
    assert paid.reservation.active is False


def test_customer_late_is_not_refunded(db_session: Session, paid: Booking) -> None:
    provider = cancel(db_session, paid, START - timedelta(hours=2), "customer")
    assert provider.called("refund") == []
    assert (paid.status, paid.deposit_status) == ("cancelled", "paid")
    assert paid.reservation.active is False


def test_garage_always_refunds(db_session: Session, paid: Booking) -> None:
    provider = cancel(db_session, paid, START - timedelta(hours=1), "garage")
    assert len(provider.called("refund")) == 1
    assert paid.status == "cancelled"


def test_waived_deposit_cancels_without_refund(db_session: Session) -> None:
    seed(db_session)
    booking = make_hold(db_session, START, START - timedelta(days=5), status="confirmed")
    booking.deposit_status = "waived"
    db_session.flush()
    provider = cancel(db_session, booking, START - timedelta(days=2), "garage")
    assert provider.calls == []
    assert (booking.status, booking.reservation.active) == ("cancelled", False)
