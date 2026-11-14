"""POST /api/holds/{reference}/checkout and DELETE /api/holds/{reference}."""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from fakes import FakeProvider
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock import utc_now
from app.models import Booking, Payment, Setting
from app.seed import seed

NOW = datetime(2026, 11, 9, 9, tzinfo=UTC)  # Monday 09:00 in London (GMT)
MOT_0800 = "2026-11-10T08:00:00+00:00"
DETAILS = {
    "name": "Sam Driver",
    "phone": "07700 900123",
    "email": "sam@example.com",
    "registration": "AB12CDE",
    "make": "Ford",
    "model": "Focus",
    "notes": "",
}


def set_now(client: TestClient, now: datetime) -> None:
    cast(FastAPI, client.app).dependency_overrides[utc_now] = lambda: now


def hold(client: TestClient) -> dict[str, Any]:
    response = client.post("/api/holds", json={"services": ["mot-test"], "start": MOT_0800})
    assert response.status_code == 201
    return cast(dict[str, Any], response.json())


def checkout(client: TestClient, created: dict[str, Any], **changes: str) -> Any:
    body = {"hold_token": created["hold_token"]} | DETAILS | changes
    return client.post(f"/api/holds/{created['reference']}/checkout", json=body)


def cancel(client: TestClient, reference: str, token: str) -> Any:
    return client.request("DELETE", f"/api/holds/{reference}", json={"hold_token": token})


def booking(session: Session, reference: str) -> Booking:
    session.expire_all()
    return session.scalars(select(Booking).where(Booking.reference == reference)).one()


def deposits(session: Session) -> list[Payment]:
    return list(session.scalars(select(Payment).where(Payment.kind == "deposit")))


def mot_starts(client: TestClient) -> list[str]:
    response = client.get(
        "/api/availability", params={"services": "mot-test", "date": "2026-11-10"}
    )
    return [slot["start"] for slot in response.json()["slots"]]


@pytest.fixture
def client(api_client: TestClient, db_session: Session) -> TestClient:
    seed(db_session)
    set_now(api_client, NOW)
    return api_client


# --- checkout --------------------------------------------------------------------


def test_checkout_saves_details_and_extends_the_hold(
    client: TestClient, db_session: Session
) -> None:
    created = hold(client)
    response = checkout(client, created, registration="ab12 cde", email="Sam@Example.com")
    assert response.status_code == 200
    assert response.json() == {
        "client_secret": "cs_fake_1_secret",
        "demo_session": None,
        "expires_in_seconds": 600,
        "amount_pence": 2000,
    }
    stored = booking(db_session, created["reference"])
    assert stored.status == "held"
    assert stored.hold_expires_at == NOW + timedelta(minutes=10)
    assert (stored.car_registration, stored.customer_email) == ("AB12CDE", "sam@example.com")
    assert stored.notes is None  # empty notes are stored as nothing
    (deposit,) = deposits(db_session)
    assert (deposit.status, deposit.amount_pence, deposit.provider) == ("open", 2000, "stripe")
    assert deposit.provider_ref == "cs_fake_1"


def test_checkout_sends_customer_email_and_amount(
    client: TestClient, fake_provider: FakeProvider, db_session: Session
) -> None:
    created = hold(client)
    checkout(client, created)
    (call,) = fake_provider.called("start_checkout")
    stored = booking(db_session, created["reference"])
    assert call["reference"] == created["reference"]
    assert call["amount_pence"] == 2000
    assert call["customer_email"] == "sam@example.com"
    assert call["idempotency_key"] == f"deposit-{stored.id}-0"
    assert created["reference"] in str(call["description"])
    assert "Tue 10 Nov 08:00" in str(call["description"])


def test_repeat_checkout_returns_same_session(
    client: TestClient, fake_provider: FakeProvider, db_session: Session
) -> None:
    created = hold(client)
    first = checkout(client, created).json()
    set_now(client, NOW + timedelta(minutes=3))
    second = checkout(client, created, name="Someone Else")
    assert second.status_code == 200
    assert second.json()["client_secret"] == first["client_secret"]
    assert second.json()["expires_in_seconds"] == 420  # the time left, not a fresh 10 minutes
    assert len(fake_provider.called("start_checkout")) == 1
    stored = booking(db_session, created["reference"])
    assert stored.hold_expires_at == NOW + timedelta(minutes=10)
    assert stored.customer_name == "Sam Driver"  # details sent on a repeat are ignored


def test_checkout_wrong_token_is_404(client: TestClient) -> None:
    response = checkout(client, hold(client) | {"hold_token": "not-the-token"})
    assert response.status_code == 404
    assert response.json() == {"detail": "Booking not found"}


def test_checkout_unknown_reference_is_404(client: TestClient) -> None:
    response = checkout(client, hold(client) | {"reference": "ZZZZ-ZZZZ"})
    assert response.status_code == 404
    assert response.json() == {"detail": "Booking not found"}


@pytest.mark.parametrize("reference", ["X" * 10, "AB%00CD"], ids=["too-long", "nul"])
def test_odd_references_give_404(client: TestClient, reference: str) -> None:
    assert checkout(client, hold(client) | {"reference": reference}).status_code == 404


def test_late_checkout_is_410_and_releases(client: TestClient, db_session: Session) -> None:
    created = hold(client)
    set_now(client, NOW + timedelta(minutes=5))  # exactly at expiry counts as expired
    response = checkout(client, created)
    assert response.status_code == 410
    assert response.json() == {"detail": "Your hold has expired"}
    released = booking(db_session, created["reference"])
    assert released.status == "expired"
    assert not released.reservation.active
    assert deposits(db_session) == []


def test_checkout_after_paid_is_409(
    client: TestClient, fake_provider: FakeProvider, db_session: Session
) -> None:
    created = hold(client)
    checkout(client, created)
    fake_provider.mark_paid("cs_fake_1")
    client.post(
        f"/api/holds/{created['reference']}/status", json={"hold_token": created["hold_token"]}
    )
    response = checkout(client, created)
    assert response.status_code == 409
    assert response.json() == {"detail": "This booking is already paid"}


def test_checkout_provider_down_is_503_and_saves_nothing(
    client: TestClient, fake_provider: FakeProvider, db_session: Session
) -> None:
    created = hold(client)
    fake_provider.fail = True
    response = checkout(client, created)
    assert response.status_code == 503
    assert response.json() == {
        "detail": "Payment is unavailable right now — please try again or call us"
    }
    stored = booking(db_session, created["reference"])
    assert stored.hold_expires_at == NOW + timedelta(minutes=5)
    assert stored.customer_name is None
    assert deposits(db_session) == []


@pytest.mark.parametrize("key", ["deposit_amount_pence", "payment_hold_minutes"])
def test_checkout_broken_payment_setting_is_503(
    client: TestClient, db_session: Session, key: str
) -> None:
    created = hold(client)
    setting = db_session.get(Setting, key)
    assert setting is not None
    setting.value = 0
    db_session.flush()
    assert checkout(client, created).status_code == 503


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("name", ""),
        ("phone", "123"),
        ("email", "sam"),
        ("registration", "A"),
        ("make", ""),
        ("model", "x" * 51),
        ("notes", "x" * 1001),
    ],
)
def test_checkout_field_rules(client: TestClient, field: str, value: str) -> None:
    response = checkout(client, hold(client), **{field: value})
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail.startswith(f"{field}: ")
    assert "Value error" not in detail


def test_old_confirm_route_is_gone(client: TestClient) -> None:
    created = hold(client)
    body = {"hold_token": created["hold_token"]} | DETAILS
    response = client.post(f"/api/holds/{created['reference']}/confirm", json=body)
    assert response.status_code in (404, 405)


# --- release ---------------------------------------------------------------------


def test_delete_releases_the_hold(client: TestClient, db_session: Session) -> None:
    created = hold(client)
    assert MOT_0800 not in mot_starts(client)
    assert cancel(client, created["reference"], created["hold_token"]).status_code == 204
    assert MOT_0800 in mot_starts(client)
    assert booking(db_session, created["reference"]).status == "expired"


def test_delete_is_idempotent(client: TestClient) -> None:
    created = hold(client)
    assert cancel(client, created["reference"], created["hold_token"]).status_code == 204
    assert cancel(client, created["reference"], created["hold_token"]).status_code == 204


def test_delete_with_wrong_token_gives_404(client: TestClient, db_session: Session) -> None:
    created = hold(client)
    assert cancel(client, created["reference"], "not-the-token").status_code == 404
    assert booking(db_session, created["reference"]).status == "held"


def test_delete_closes_the_open_checkout(
    client: TestClient, fake_provider: FakeProvider, db_session: Session
) -> None:
    created = hold(client)
    checkout(client, created)
    assert cancel(client, created["reference"], created["hold_token"]).status_code == 204
    assert fake_provider.called("close_checkout") == [{"session_ref": "cs_fake_1"}]
    (deposit,) = deposits(db_session)
    assert deposit.status == "expired"
    assert booking(db_session, created["reference"]).status == "expired"


def test_delete_when_payment_got_in_confirms(
    client: TestClient, fake_provider: FakeProvider, db_session: Session
) -> None:
    created = hold(client)
    checkout(client, created)
    fake_provider.mark_paid("cs_fake_1")  # the customer paid a moment before leaving
    response = cancel(client, created["reference"], created["hold_token"])
    assert response.status_code == 409
    assert response.json() == {"detail": "This booking is already confirmed"}
    stored = booking(db_session, created["reference"])
    assert (stored.status, stored.deposit_status) == ("confirmed", "paid")
    assert stored.reservation.active


def test_delete_with_provider_down_still_releases(
    client: TestClient, fake_provider: FakeProvider, db_session: Session
) -> None:
    created = hold(client)
    checkout(client, created)
    fake_provider.fail = True
    assert cancel(client, created["reference"], created["hold_token"]).status_code == 204
    assert booking(db_session, created["reference"]).status == "expired"
    (deposit,) = deposits(db_session)
    assert deposit.status == "open"  # the worker closes it later


def test_delete_confirmed_gives_409_and_changes_nothing(
    client: TestClient, fake_provider: FakeProvider, db_session: Session
) -> None:
    created = hold(client)
    checkout(client, created)
    fake_provider.mark_paid("cs_fake_1")
    client.post(
        f"/api/holds/{created['reference']}/status", json={"hold_token": created["hold_token"]}
    )
    response = cancel(client, created["reference"], created["hold_token"])
    assert response.status_code == 409
    stored = booking(db_session, created["reference"])
    assert stored.status == "confirmed"
    assert stored.reservation.active


def test_checkout_provider_failure_is_logged_with_its_reason(
    client: TestClient, fake_provider: FakeProvider, caplog: pytest.LogCaptureFixture
) -> None:
    created = hold(client)
    fake_provider.fail = True
    with caplog.at_level(logging.WARNING):
        assert checkout(client, created).status_code == 503
    assert created["reference"] in caplog.text
    assert "fake provider told to fail" in caplog.text  # the provider's reason, never a key
