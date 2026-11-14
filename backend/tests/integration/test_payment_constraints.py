"""The database refuses payments that break the money rules, whatever the code does."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from factories import make_deposit, make_hold
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Booking, Payment, PaymentEvent
from app.seed import seed

START = datetime(2026, 11, 10, 8, tzinfo=UTC)
NOW = datetime(2026, 11, 9, 9, tzinfo=UTC)


@pytest.fixture
def held(db_session: Session) -> Booking:
    seed(db_session)
    return make_hold(db_session, START, NOW + timedelta(minutes=10))


def refund(session: Session, deposit: Payment, ref: str, status: str = "pending") -> Payment:
    payment = Payment(
        booking_id=deposit.booking_id,
        kind="refund",
        provider="stripe",
        provider_ref=ref,
        amount_pence=deposit.amount_pence,
        status=status,
        refund_of=deposit.id,
    )
    session.add(payment)
    session.flush()
    return payment


def rejects(session: Session, **changes: Any) -> None:
    with pytest.raises(IntegrityError), session.begin_nested():
        session.add(Payment(**changes))
        session.flush()


def test_open_deposit_can_be_stored(db_session: Session, held: Booking) -> None:
    deposit = make_deposit(db_session, held)
    assert deposit.id is not None
    assert held.deposit_status == "unpaid"


def test_unknown_deposit_status_is_rejected(db_session: Session, held: Booking) -> None:
    held.deposit_status = "maybe"
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_confirmed_booking_needs_a_paid_or_waived_deposit(
    db_session: Session, held: Booking
) -> None:
    for key, value in {
        "customer_name": "Sam Driver",
        "customer_phone": "07700 900123",
        "customer_email": "sam@example.com",
        "car_registration": "AB12CDE",
        "car_make": "Ford",
        "car_model": "Focus",
    }.items():
        setattr(held, key, value)
    held.status = "confirmed"  # deposit_status is still "unpaid"
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_one_open_deposit_per_booking(db_session: Session, held: Booking) -> None:
    make_deposit(db_session, held, ref="cs_test_1")
    with pytest.raises(IntegrityError):
        make_deposit(db_session, held, ref="cs_test_2")


def test_provider_ref_is_unique(db_session: Session, held: Booking) -> None:
    make_deposit(db_session, held, ref="cs_test_1", status="expired")
    with pytest.raises(IntegrityError):
        make_deposit(db_session, held, ref="cs_test_1")


def test_amount_must_be_positive(db_session: Session, held: Booking) -> None:
    with pytest.raises(IntegrityError):
        make_deposit(db_session, held, amount_pence=0)


def test_refund_needs_refund_of(db_session: Session, held: Booking) -> None:
    common = {"booking_id": held.id, "provider": "stripe", "amount_pence": 2000}
    rejects(db_session, kind="refund", provider_ref="re_1", status="pending", **common)


def test_deposit_status_must_suit_kind(db_session: Session, held: Booking) -> None:
    common = {"booking_id": held.id, "provider": "stripe", "amount_pence": 2000}
    rejects(db_session, kind="deposit", provider_ref="cs_1", status="succeeded", **common)
    rejects(db_session, kind="payout", provider_ref="cs_2", status="open", **common)


def test_one_live_refund_per_deposit(db_session: Session, held: Booking) -> None:
    deposit = make_deposit(db_session, held, status="paid")
    refund(db_session, deposit, "re_1")
    with pytest.raises(IntegrityError):
        refund(db_session, deposit, "re_2")


def test_failed_refund_allows_another(db_session: Session, held: Booking) -> None:
    deposit = make_deposit(db_session, held, status="paid")
    refund(db_session, deposit, "re_1", status="failed")
    assert refund(db_session, deposit, "re_2").id is not None


def test_event_ids_are_unique(db_session: Session) -> None:
    db_session.add(PaymentEvent(provider="stripe", event_id="evt_1", type="x"))
    db_session.flush()
    db_session.add(PaymentEvent(provider="stripe", event_id="evt_1", type="x"))
    with pytest.raises(IntegrityError):
        db_session.flush()
