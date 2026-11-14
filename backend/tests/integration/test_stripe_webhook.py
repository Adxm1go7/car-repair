"""POST /api/stripe/webhook: signed, idempotent, and never trusting the event body alone."""

import time
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from factories import make_deposit, make_hold
from fakes import FakeProvider
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from stripe_signing import event, signed

from app.clock import utc_now
from app.models import Booking, Payment, PaymentEvent
from app.payments.service import complete_deposit
from app.seed import seed

NOW = datetime(2026, 11, 9, 9, tzinfo=UTC)
START = datetime(2026, 11, 10, 8, tzinfo=UTC)
URL = "/api/stripe/webhook"


@pytest.fixture
def client(webhook_client: TestClient, db_session: Session) -> TestClient:
    seed(db_session)
    # Commit (a savepoint here, still undone after the test) so the route's own rollback on
    # a failed event can't take the test's setup data with it.
    db_session.commit()
    cast(FastAPI, webhook_client.app).dependency_overrides[utc_now] = lambda: NOW
    return webhook_client


@pytest.fixture
def paying(db_session: Session) -> Booking:
    """A held booking whose payment form cs_fake_1 is open."""
    booking = make_hold(db_session, START, NOW + timedelta(minutes=10), details=True)
    make_deposit(db_session, booking, ref="cs_fake_1")
    return booking


def post(client: TestClient, body: bytes, headers: dict[str, str] | None = None) -> Any:
    return client.post(URL, content=body, headers=signed(body) if headers is None else headers)


def reload(session: Session, booking: Booking) -> Booking:
    session.expire_all()
    fresh = session.get(Booking, booking.id)
    assert fresh is not None
    return fresh


def event_rows(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(PaymentEvent)) or 0


def deposit(session: Session) -> Payment:
    session.expire_all()
    return session.scalars(select(Payment).where(Payment.provider_ref == "cs_fake_1")).one()


def late_refund_setup(session: Session, provider: FakeProvider) -> Booking:
    """A paid deposit for a time someone else now holds: completing it refunds."""
    late = make_hold(session, START, NOW - timedelta(minutes=1), status="expired", details=True)
    make_deposit(session, late, ref="cs_fake_1")
    make_hold(session, START, NOW + timedelta(minutes=5))
    provider.mark_paid("cs_fake_1")
    session.commit()  # see `client`
    return late


# --- checkout sessions -----------------------------------------------------------


def test_completed_event_confirms_the_booking(
    client: TestClient, db_session: Session, paying: Booking, fake_provider: FakeProvider
) -> None:
    fake_provider.mark_paid("cs_fake_1")
    response = post(client, event("checkout_session_completed"))
    assert response.status_code == 200
    booking = reload(db_session, paying)
    assert (booking.status, booking.deposit_status) == ("confirmed", "paid")
    assert event_rows(db_session) == 1


def test_duplicate_event_changes_nothing(
    client: TestClient, db_session: Session, paying: Booking, fake_provider: FakeProvider
) -> None:
    fake_provider.mark_paid("cs_fake_1")
    body = event("checkout_session_completed")
    assert post(client, body).status_code == 200
    assert post(client, body).status_code == 200
    assert event_rows(db_session) == 1
    assert len(fake_provider.called("get_checkout")) == 1  # the repeat was never handled
    assert reload(db_session, paying).confirmed_at == NOW


def test_webhook_after_poll_confirmed_is_harmless(
    client: TestClient, db_session: Session, paying: Booking, fake_provider: FakeProvider
) -> None:
    fake_provider.mark_paid("cs_fake_1")
    complete_deposit(db_session, fake_provider, "cs_fake_1", NOW - timedelta(seconds=5))
    assert post(client, event("checkout_session_completed")).status_code == 200
    booking = reload(db_session, paying)
    assert booking.confirmed_at == NOW - timedelta(seconds=5)
    assert fake_provider.called("refund") == []


def test_completed_event_for_an_unpaid_session_confirms_nothing(
    client: TestClient, db_session: Session, paying: Booking
) -> None:
    # The body claims "paid", but Stripe (the fake) says it isn't: the body is not trusted.
    assert post(client, event("checkout_session_completed")).status_code == 200
    assert reload(db_session, paying).status == "held"


def test_expired_after_completed_leaves_booking_confirmed(
    client: TestClient, db_session: Session, paying: Booking, fake_provider: FakeProvider
) -> None:
    fake_provider.mark_paid("cs_fake_1")
    post(client, event("checkout_session_completed"))
    assert post(client, event("checkout_session_expired")).status_code == 200
    assert reload(db_session, paying).status == "confirmed"
    assert deposit(db_session).status == "paid"


def test_expired_event_marks_open_deposit_expired(
    client: TestClient, db_session: Session, paying: Booking
) -> None:
    assert post(client, event("checkout_session_expired")).status_code == 200
    assert deposit(db_session).status == "expired"
    assert reload(db_session, paying).status == "held"  # the hold rules decide the booking


def test_unknown_session_is_200_and_ignored(client: TestClient, db_session: Session) -> None:
    body = event("checkout_session_completed", object_id="cs_nobody")
    assert post(client, body).status_code == 200
    assert event_rows(db_session) == 1


def test_unhandled_event_is_recorded_and_ignored(client: TestClient, db_session: Session) -> None:
    assert post(client, event("payment_intent_failed")).status_code == 200
    assert event_rows(db_session) == 1


# --- refunds ---------------------------------------------------------------------


def test_refund_update_before_the_row_exists_is_503_and_unrecorded(
    client: TestClient, db_session: Session, fake_provider: FakeProvider
) -> None:
    body = event("refund_updated")  # refund re_fake_1, which we haven't stored yet
    assert post(client, body).status_code == 503
    assert event_rows(db_session) == 0

    late = late_refund_setup(db_session, fake_provider)
    complete_deposit(db_session, fake_provider, "cs_fake_1", NOW)  # creates re_fake_1
    fake_provider.refunds["re_fake_1"] = "succeeded"
    assert post(client, body).status_code == 200  # Stripe's retry
    assert reload(db_session, late).deposit_status == "refunded"
    assert event_rows(db_session) == 1


def test_failure_inside_handling_rolls_back_the_event(
    client: TestClient, db_session: Session, fake_provider: FakeProvider
) -> None:
    late = late_refund_setup(db_session, fake_provider)
    fake_provider.fail_calls.add("refund")
    body = event("checkout_session_completed")
    assert post(client, body).status_code == 500
    assert event_rows(db_session) == 0
    assert deposit(db_session).status == "open"

    fake_provider.fail_calls.clear()
    assert post(client, body).status_code == 200  # Stripe retries the same event
    assert reload(db_session, late).deposit_status == "refund_pending"


# --- signatures ------------------------------------------------------------------


def test_bad_signature_is_400(client: TestClient, db_session: Session) -> None:
    body = event("checkout_session_completed")
    assert post(client, body, signed(body, secret="whsec_wrong")).status_code == 400  # noqa: S106
    assert event_rows(db_session) == 0


def test_missing_signature_is_400(client: TestClient) -> None:
    body = event("checkout_session_completed")
    assert post(client, body, {"Content-Type": "application/json"}).status_code == 400


def test_tampered_body_is_400(client: TestClient) -> None:
    body = event("checkout_session_completed")
    headers = signed(body)
    tampered = body.replace(b"cs_fake_1", b"cs_fake_2")
    assert post(client, tampered, headers).status_code == 400


def test_old_timestamp_is_400(client: TestClient) -> None:
    body = event("checkout_session_completed")
    old = signed(body, timestamp=int(time.time()) - 600)
    assert post(client, body, old).status_code == 400


def test_no_secret_configured_is_503(api_client: TestClient) -> None:
    body = event("checkout_session_completed")
    assert post(api_client, body).status_code == 503
