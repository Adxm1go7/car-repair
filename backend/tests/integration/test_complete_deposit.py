"""complete_deposit is the only way to a paid booking: it confirms, re-takes or refunds, once."""

from datetime import UTC, datetime, timedelta

import pytest
from factories import make_deposit, make_hold
from fakes import FakeProvider
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Booking, Payment
from app.payments.provider import PaymentUnavailable
from app.payments.service import apply_refund_update, close_open_deposit, complete_deposit
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


def held_with_deposit(
    session: Session, expires_at: datetime = NOW + timedelta(minutes=10)
) -> tuple[Booking, Payment]:
    booking = make_hold(session, START, expires_at, details=True)
    return booking, make_deposit(session, booking, ref=REF)


def late_with_rival(session: Session) -> tuple[Booking, Payment]:
    """A released hold whose payment came in after someone else took the same time."""
    late = make_hold(session, START, NOW - timedelta(minutes=1), status="expired", details=True)
    deposit = make_deposit(session, late, ref=REF)
    make_hold(session, START, NOW + timedelta(minutes=5))
    return late, deposit


def refunds(session: Session) -> list[Payment]:
    return list(session.scalars(select(Payment).where(Payment.kind == "refund")))


def reload(session: Session, booking: Booking) -> Booking:
    session.expire_all()
    fresh = session.get(Booking, booking.id)
    assert fresh is not None
    return fresh


def payment(session: Session, deposit: Payment) -> Payment:
    session.expire_all()
    fresh = session.get(Payment, deposit.id)
    assert fresh is not None
    return fresh


def test_paid_held_booking_is_confirmed(seeded: Session, provider: FakeProvider) -> None:
    booking, deposit = held_with_deposit(seeded)
    provider.mark_paid(REF)
    assert complete_deposit(seeded, provider, REF, NOW) is not None
    booking = reload(seeded, booking)
    assert (booking.status, booking.deposit_status) == ("confirmed", "paid")
    assert booking.confirmed_at == NOW
    deposit = payment(seeded, deposit)
    assert (deposit.status, deposit.payment_intent_ref) == ("paid", f"pi_{REF}")


def test_held_past_its_time_but_unreleased_is_confirmed(
    seeded: Session, provider: FakeProvider
) -> None:
    booking, _ = held_with_deposit(seeded, expires_at=NOW - timedelta(minutes=1))
    provider.mark_paid(REF)
    complete_deposit(seeded, provider, REF, NOW)
    assert reload(seeded, booking).status == "confirmed"


def test_unpaid_session_changes_nothing(seeded: Session, provider: FakeProvider) -> None:
    booking, _ = held_with_deposit(seeded)
    assert complete_deposit(seeded, provider, REF, NOW) is None
    booking = reload(seeded, booking)
    assert (booking.status, booking.deposit_status) == ("held", "unpaid")


def test_unknown_session_returns_none(seeded: Session, provider: FakeProvider) -> None:
    assert complete_deposit(seeded, provider, "cs_nobody", NOW) is None
    assert provider.called("get_checkout") == []


def test_completing_twice_changes_nothing(seeded: Session, provider: FakeProvider) -> None:
    booking, _ = held_with_deposit(seeded)
    provider.mark_paid(REF)
    complete_deposit(seeded, provider, REF, NOW)
    complete_deposit(seeded, provider, REF, NOW + timedelta(minutes=1))
    assert reload(seeded, booking).confirmed_at == NOW
    assert len(provider.called("get_checkout")) == 1  # the second call stopped at "paid"


def test_late_payment_time_still_free_is_confirmed(seeded: Session, provider: FakeProvider) -> None:
    booking = make_hold(seeded, START, NOW - timedelta(minutes=1), status="expired", details=True)
    make_deposit(seeded, booking, ref=REF)
    provider.mark_paid(REF)
    complete_deposit(seeded, provider, REF, NOW)
    booking = reload(seeded, booking)
    assert (booking.status, booking.deposit_status) == ("confirmed", "paid")
    assert booking.reservation.active is True
    assert refunds(seeded) == []


def test_late_payment_time_taken_refunds_once(seeded: Session, provider: FakeProvider) -> None:
    late, _ = late_with_rival(seeded)
    provider.mark_paid(REF)

    complete_deposit(seeded, provider, REF, NOW)
    complete_deposit(seeded, provider, REF, NOW)

    late = reload(seeded, late)
    assert (late.status, late.deposit_status) == ("expired", "refund_pending")
    assert late.reservation.active is False
    (refund,) = refunds(seeded)
    assert (refund.status, refund.amount_pence) == ("pending", 2000)
    (call,) = provider.called("refund")
    assert call["payment_intent_ref"] == f"pi_{REF}"
    assert call["idempotency_key"] == f"refund-{REF}-0"  # the provider's session id: unique


def test_refund_failure_rolls_back(seeded: Session, provider: FakeProvider) -> None:
    _, deposit = late_with_rival(seeded)
    provider.mark_paid(REF)
    provider.fail_calls.add("refund")

    with pytest.raises(PaymentUnavailable), seeded.begin_nested():
        complete_deposit(seeded, provider, REF, NOW)

    assert refunds(seeded) == []
    assert payment(seeded, deposit).status == "open"  # so Stripe's retry runs it all again


def refunded_late_booking(seeded: Session, provider: FakeProvider) -> tuple[Booking, Payment]:
    late, _ = late_with_rival(seeded)
    provider.mark_paid(REF)
    complete_deposit(seeded, provider, REF, NOW)
    (refund,) = refunds(seeded)
    return late, refund


def test_refund_update_marks_refunded(seeded: Session, provider: FakeProvider) -> None:
    late, refund = refunded_late_booking(seeded, provider)
    provider.refunds[refund.provider_ref] = "succeeded"
    assert apply_refund_update(seeded, provider, refund.provider_ref) is True
    assert reload(seeded, late).deposit_status == "refunded"
    assert payment(seeded, refund).status == "succeeded"


def test_failed_refund_marks_refund_failed(seeded: Session, provider: FakeProvider) -> None:
    late, refund = refunded_late_booking(seeded, provider)
    provider.refunds[refund.provider_ref] = "failed"
    apply_refund_update(seeded, provider, refund.provider_ref)
    assert reload(seeded, late).deposit_status == "refund_failed"


def test_refund_update_for_unknown_refund_returns_false(
    seeded: Session, provider: FakeProvider
) -> None:
    assert apply_refund_update(seeded, provider, "re_nobody") is False


def test_close_open_deposit_marks_expired(seeded: Session, provider: FakeProvider) -> None:
    booking, deposit = held_with_deposit(seeded)
    assert close_open_deposit(seeded, provider, booking, NOW) is None
    assert payment(seeded, deposit).status == "expired"


def test_close_open_deposit_completes_when_payment_got_in(
    seeded: Session, provider: FakeProvider
) -> None:
    booking, _ = held_with_deposit(seeded)
    provider.mark_paid(REF)
    assert close_open_deposit(seeded, provider, booking, NOW) is not None
    assert reload(seeded, booking).status == "confirmed"


def test_close_with_no_open_deposit_does_nothing(seeded: Session, provider: FakeProvider) -> None:
    booking = make_hold(seeded, START, NOW + timedelta(minutes=5))
    assert close_open_deposit(seeded, provider, booking, NOW) is None
    assert provider.calls == []
