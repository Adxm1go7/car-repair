"""POST /api/bookings/{reference}/view and /cancel: the customer's private booking link."""

from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from factories import make_deposit, make_hold
from fakes import FakeProvider
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.bookings.links import create_link
from app.clock import utc_now
from app.models import Booking, EmailLog
from app.seed import seed

START = datetime(2026, 11, 20, 9, tzinfo=UTC)
NOW = START - timedelta(days=5)
INSIDE_WINDOW = START - timedelta(hours=2)


def set_now(client: TestClient, now: datetime) -> None:
    cast(FastAPI, client.app).dependency_overrides[utc_now] = lambda: now


def paid_booking(session: Session, start: datetime = START) -> Booking:
    booking = make_hold(session, start, start - timedelta(days=6), status="confirmed")
    deposit = make_deposit(session, booking, ref=f"cs_{booking.reference}", status="paid")
    deposit.payment_intent_ref = f"pi_{booking.reference}"
    session.flush()
    return booking


@pytest.fixture
def client(api_client: TestClient, db_session: Session) -> TestClient:
    seed(db_session)
    set_now(api_client, NOW)
    return api_client


@pytest.fixture
def booking(client: TestClient, db_session: Session) -> Booking:
    return paid_booking(db_session)


@pytest.fixture
def token(db_session: Session, booking: Booking) -> str:
    token = create_link(db_session, booking)
    db_session.commit()  # a savepoint: still undone after the test
    return token


def cancellations(session: Session) -> list[EmailLog]:
    session.expire_all()
    return list(session.scalars(select(EmailLog).where(EmailLog.template == "cancellation")))


def view(client: TestClient, reference: str, token: str) -> tuple[int, dict[str, object]]:
    response = client.post(f"/api/bookings/{reference}/view", json={"token": token})
    return response.status_code, response.json()


def cancel(client: TestClient, reference: str, token: str) -> tuple[int, dict[str, object]]:
    response = client.post(f"/api/bookings/{reference}/cancel", json={"token": token})
    return response.status_code, response.json()


def test_view_shows_booking_and_can_cancel(
    client: TestClient, booking: Booking, token: str
) -> None:
    status, body = view(client, booking.reference, token)
    assert status == 200
    summary = cast(dict[str, object], body["summary"])
    assert summary["reference"] == booking.reference
    assert summary["status"] == "confirmed"
    assert summary["start"] == "2026-11-20T09:00:00+00:00"
    assert summary["deposit_paid_pence"] == 2000
    assert body["deposit_status"] == "paid"
    assert body["can_cancel"] is True
    assert body["refund_if_cancelled"] is True
    assert body["free_cancellation_until"] == "2026-11-19T09:00:00+00:00"


def test_view_inside_window_cannot_cancel(client: TestClient, booking: Booking, token: str) -> None:
    set_now(client, INSIDE_WINDOW)
    status, body = view(client, booking.reference, token)
    assert status == 200
    assert body["can_cancel"] is False
    assert body["refund_if_cancelled"] is False


@pytest.mark.parametrize("case", ["wrong", "expired", "other_reference"])
def test_view_with_wrong_expired_or_other_reference_token_is_404(
    client: TestClient, db_session: Session, booking: Booking, token: str, case: str
) -> None:
    reference, used = booking.reference, token
    if case == "wrong":
        used = token[:-1] + ("A" if token[-1] != "A" else "B")
    elif case == "expired":
        set_now(client, booking.end_at + timedelta(days=7))
    else:
        other = paid_booking(db_session, START + timedelta(days=1))
        db_session.commit()
        reference = other.reference
    status, body = view(client, reference, used)
    assert status == 404
    assert body == {"detail": "This link isn't valid"}


def test_view_with_oversized_token_is_404(client: TestClient, booking: Booking) -> None:
    status, body = view(client, booking.reference, "x" * 5000)
    assert status == 404
    assert body == {"detail": "This link isn't valid"}


def test_cancel_refunds_and_queues_cancellation(
    client: TestClient,
    db_session: Session,
    fake_provider: FakeProvider,
    booking: Booking,
    token: str,
) -> None:
    status, body = cancel(client, booking.reference, token)
    assert status == 200
    assert cast(dict[str, object], body["summary"])["status"] == "cancelled"
    assert body["deposit_status"] == "refund_pending"
    assert body["can_cancel"] is False
    assert len(fake_provider.called("refund")) == 1
    (email,) = cancellations(db_session)
    assert (email.booking_id, email.status) == (booking.id, "queued")
    assert booking.reservation.active is False


def test_cancel_inside_window_is_409_too_late_and_changes_nothing(
    client: TestClient,
    db_session: Session,
    fake_provider: FakeProvider,
    booking: Booking,
    token: str,
) -> None:
    set_now(client, INSIDE_WINDOW)
    status, body = cancel(client, booking.reference, token)
    assert status == 409
    assert body == {"detail": "too_late"}
    assert fake_provider.called("refund") == []
    assert cancellations(db_session) == []
    assert (booking.status, booking.reservation.active) == ("confirmed", True)


def test_cancel_twice_refunds_once(
    client: TestClient,
    db_session: Session,
    fake_provider: FakeProvider,
    booking: Booking,
    token: str,
) -> None:
    assert cancel(client, booking.reference, token)[0] == 200
    status, body = cancel(client, booking.reference, token)
    assert status == 409
    assert body == {"detail": "not_cancellable"}
    assert len(fake_provider.called("refund")) == 1
    assert len(cancellations(db_session)) == 1


def test_cancel_when_refund_unavailable_is_503_and_changes_nothing(
    client: TestClient,
    db_session: Session,
    fake_provider: FakeProvider,
    booking: Booking,
    token: str,
) -> None:
    fake_provider.fail_calls = {"refund"}
    status, body = cancel(client, booking.reference, token)
    assert status == 503
    assert body == {"detail": "We couldn't cancel just now"}
    assert cancellations(db_session) == []
    assert (booking.status, booking.deposit_status) == ("confirmed", "paid")
    assert booking.reservation.active is True
