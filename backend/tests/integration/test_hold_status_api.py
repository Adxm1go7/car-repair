"""POST /api/holds/{reference}/status: the page asks this after Stripe says "paid"."""

from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from factories import make_deposit, make_hold
from fakes import FakeProvider
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock import utc_now
from app.models import Booking
from app.seed import seed

NOW = datetime(2026, 11, 9, 9, tzinfo=UTC)
MOT_0800 = "2026-11-10T08:00:00+00:00"
DETAILS = {
    "name": "Sam Driver",
    "phone": "07700 900123",
    "email": "sam@example.com",
    "registration": "AB12CDE",
    "make": "Ford",
    "model": "Focus",
}


def set_now(client: TestClient, now: datetime) -> None:
    cast(FastAPI, client.app).dependency_overrides[utc_now] = lambda: now


@pytest.fixture
def client(api_client: TestClient, db_session: Session) -> TestClient:
    seed(db_session)
    set_now(api_client, NOW)
    return api_client


def paying(client: TestClient) -> dict[str, Any]:
    """A hold that has moved on to payment."""
    created = cast(
        dict[str, Any],
        client.post("/api/holds", json={"services": ["mot-test"], "start": MOT_0800}).json(),
    )
    body = {"hold_token": created["hold_token"]} | DETAILS
    assert client.post(f"/api/holds/{created['reference']}/checkout", json=body).status_code == 200
    return created


def status(client: TestClient, created: dict[str, Any], token: str | None = None) -> Any:
    body = {"hold_token": token or created["hold_token"]}
    return client.post(f"/api/holds/{created['reference']}/status", json=body)


def test_status_while_waiting_is_held(client: TestClient) -> None:
    response = status(client, paying(client))
    assert response.status_code == 200
    assert response.json() == {
        "status": "held",
        "deposit_status": "unpaid",
        "payment_pending": True,
        "summary": None,
    }


def test_status_confirms_when_provider_says_paid(
    client: TestClient, fake_provider: FakeProvider
) -> None:
    created = paying(client)
    fake_provider.mark_paid("cs_fake_1")  # no webhook has arrived
    body = status(client, created).json()
    assert (body["status"], body["deposit_status"]) == ("confirmed", "paid")
    summary = body["summary"]
    assert summary["reference"] == created["reference"]
    assert summary["deposit_paid_pence"] == 2000
    assert (summary["registration"], summary["make"], summary["model"]) == (
        "AB12CDE",
        "Ford",
        "Focus",
    )


def test_status_after_release_is_expired(client: TestClient) -> None:
    created = paying(client)
    client.request(
        "DELETE", f"/api/holds/{created['reference']}", json={"hold_token": created["hold_token"]}
    )
    assert status(client, created).json() == {
        "status": "expired",
        "deposit_status": "unpaid",
        "payment_pending": False,  # the form was closed: nothing can be charged now
        "summary": None,
    }


def test_status_past_the_payment_hold_releases(client: TestClient, db_session: Session) -> None:
    created = paying(client)
    set_now(client, NOW + timedelta(minutes=10))
    assert status(client, created).json()["status"] == "expired"
    db_session.expire_all()
    stored = db_session.scalars(
        select(Booking).where(Booking.reference == created["reference"])
    ).one()
    assert not stored.reservation.active


def test_status_shows_refund(
    client: TestClient, fake_provider: FakeProvider, db_session: Session
) -> None:
    start = datetime(2026, 11, 10, 10, tzinfo=UTC)
    late = make_hold(db_session, start, NOW - timedelta(minutes=1), status="expired", details=True)
    make_deposit(db_session, late, ref="cs_late")
    make_hold(db_session, start, NOW + timedelta(minutes=5))  # the time went to someone else
    fake_provider.mark_paid("cs_late")
    body = {"hold_token": "t"}  # factories.TEST_TOKEN
    response = client.post(f"/api/holds/{late.reference}/status", json=body)
    assert response.json() == {
        "status": "expired",
        "deposit_status": "refund_pending",
        "payment_pending": False,
        "summary": None,
    }


def test_status_wrong_token_is_404(client: TestClient) -> None:
    response = status(client, paying(client), token="not-the-token")  # noqa: S106
    assert response.status_code == 404


def test_status_provider_down_says_held(client: TestClient, fake_provider: FakeProvider) -> None:
    created = paying(client)
    fake_provider.mark_paid("cs_fake_1")
    fake_provider.fail = True
    assert status(client, created).json()["status"] == "held"


def test_status_after_a_release_stripe_could_not_close_says_payment_pending(
    client: TestClient, fake_provider: FakeProvider
) -> None:
    """Released while Stripe was unreachable: the form may still take a payment, so the page
    must not tell the customer they haven't been charged."""
    created = paying(client)
    fake_provider.fail = True
    client.request(
        "DELETE", f"/api/holds/{created['reference']}", json={"hold_token": created["hold_token"]}
    )
    body = status(client, created).json()
    assert (body["status"], body["deposit_status"], body["payment_pending"]) == (
        "expired",
        "unpaid",
        True,
    )
