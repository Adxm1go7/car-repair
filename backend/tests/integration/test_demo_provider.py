"""Demo payments: the deposit row is the session, and paying marks its payment intent."""

from datetime import UTC, datetime, timedelta

from factories import make_deposit, make_hold
from sqlalchemy.orm import Session

from app.payments.demo_provider import DemoProvider
from app.seed import seed

START = datetime(2026, 11, 10, 8, tzinfo=UTC)
NOW = datetime(2026, 11, 9, 9, tzinfo=UTC)


def demo_deposit(session: Session) -> str:
    seed(session)
    booking = make_hold(session, START, NOW + timedelta(minutes=10))
    return make_deposit(session, booking, ref="demo_abc", provider="demo").provider_ref


def test_demo_checkout_is_unpaid_until_marked(db_session: Session) -> None:
    ref = demo_deposit(db_session)
    provider = DemoProvider(db_session)
    state = provider.get_checkout(ref)
    assert (state.status, state.paid, state.client_secret) == ("open", False, None)
    provider.mark_paid(ref)
    state = provider.get_checkout(ref)
    assert (state.status, state.paid) == ("complete", True)
    assert state.payment_intent_ref is not None
    assert state.payment_intent_ref.startswith("demo_pi_")


def test_demo_start_makes_a_demo_ref() -> None:
    started = DemoProvider(None).start_checkout(  # type: ignore[arg-type]
        reference="R",
        amount_pence=2000,
        customer_email="e@x.io",
        description="d",
        idempotency_key="k",
    )
    assert started.session_ref.startswith("demo_")
    assert started.client_secret is None


def test_demo_close_refuses_once_paid(db_session: Session) -> None:
    ref = demo_deposit(db_session)
    provider = DemoProvider(db_session)
    assert provider.close_checkout(ref) is True
    provider.mark_paid(ref)
    assert provider.close_checkout(ref) is False


def test_demo_refund_succeeds(db_session: Session) -> None:
    provider = DemoProvider(db_session)
    refund = provider.refund(payment_intent_ref="demo_pi_x", amount_pence=2000, idempotency_key="k")
    assert refund.status == "succeeded"
    assert provider.get_refund(refund.refund_ref).status == "succeeded"
