"""A late payment whose refund call fails must stay retryable, through every path that can
complete it. Otherwise the customer is charged with no booking and no refund, and nothing
ever tries again (the worker and the webhook only act on an open deposit)."""

from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from factories import TEST_TOKEN, make_deposit, make_hold
from fakes import FakeProvider
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock import utc_now
from app.models import Booking, Payment
from app.seed import seed

NOW = datetime(2026, 11, 9, 9, tzinfo=UTC)
START = datetime(2026, 11, 10, 8, tzinfo=UTC)
REF = "cs_fake_late"


@pytest.fixture
def late(api_client: TestClient, db_session: Session, fake_provider: FakeProvider) -> Booking:
    """Released, paid at Stripe at the last moment, its time now someone else's, and
    Stripe failing on refunds."""
    seed(db_session)
    cast(FastAPI, api_client.app).dependency_overrides[utc_now] = lambda: NOW
    booking = make_hold(
        db_session, START, NOW - timedelta(minutes=1), status="expired", details=True
    )
    make_deposit(db_session, booking, ref=REF)
    make_hold(db_session, START, NOW + timedelta(minutes=5))  # the rival
    db_session.commit()  # a savepoint: still undone after the test
    fake_provider.mark_paid(REF)
    fake_provider.fail_calls.add("refund")
    return booking


def deposit(session: Session) -> Payment:
    session.expire_all()
    return session.scalars(select(Payment).where(Payment.provider_ref == REF)).one()


def refunds(session: Session) -> list[Payment]:
    return list(session.scalars(select(Payment).where(Payment.kind == "refund")))


def body() -> dict[str, Any]:
    return {"hold_token": TEST_TOKEN}


def test_delete_keeps_a_failed_late_refund_retryable(
    api_client: TestClient, db_session: Session, late: Booking
) -> None:
    api_client.request("DELETE", f"/api/holds/{late.reference}", json=body())
    assert deposit(db_session).status == "open"  # so the worker or webhook tries again
    assert refunds(db_session) == []


def test_status_keeps_a_failed_late_refund_retryable(
    api_client: TestClient, db_session: Session, late: Booking
) -> None:
    response = api_client.post(f"/api/holds/{late.reference}/status", json=body())
    assert response.status_code == 200
    assert deposit(db_session).status == "open"
    assert refunds(db_session) == []


def test_the_worker_then_refunds_it(
    api_client: TestClient, db_session: Session, late: Booking, fake_provider: FakeProvider
) -> None:
    from app.worker import close_stale_checkouts

    api_client.request("DELETE", f"/api/holds/{late.reference}", json=body())
    fake_provider.fail_calls.clear()  # Stripe is back
    close_stale_checkouts(db_session, fake_provider, NOW + timedelta(minutes=1))
    assert deposit(db_session).status == "paid"
    (refund,) = refunds(db_session)
    assert refund.status == "pending"
