"""POST /api/holds/{reference}/confirm and DELETE /api/holds/{reference}."""

from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock import utc_now
from app.models import Booking
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


def confirm(client: TestClient, created: dict[str, Any], **changes: str) -> Any:
    body = {"hold_token": created["hold_token"]} | DETAILS | changes
    return client.post(f"/api/holds/{created['reference']}/confirm", json=body)


def cancel(client: TestClient, reference: str, token: str) -> Any:
    return client.request("DELETE", f"/api/holds/{reference}", json={"hold_token": token})


def booking(session: Session, reference: str) -> Booking:
    session.expire_all()
    return session.scalars(select(Booking).where(Booking.reference == reference)).one()


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


# --- confirm ---------------------------------------------------------------------


def test_confirm_stores_normalised_details(client: TestClient, db_session: Session) -> None:
    created = hold(client)
    response = confirm(client, created, registration="ab12 cde", email="Sam@Example.com")
    assert response.status_code == 200
    body = response.json()
    assert (body["reference"], body["status"], body["registration"], body["start"]) == (
        created["reference"],
        "confirmed",
        "AB12CDE",
        MOT_0800,
    )
    assert body["end"] == "2026-11-10T09:00:00+00:00"
    assert [s["slug"] for s in body["services"]] == ["mot-test"]
    assert (body["make"], body["model"]) == ("Ford", "Focus")

    stored = booking(db_session, created["reference"])
    assert stored.status == "confirmed"
    assert stored.customer_email == "sam@example.com"
    assert stored.notes is None  # empty notes are stored as nothing
    assert stored.confirmed_at == NOW
    assert stored.reservation.active


def test_repeat_confirm_is_idempotent(client: TestClient, db_session: Session) -> None:
    created = hold(client)
    first = confirm(client, created)
    set_now(client, NOW + timedelta(minutes=30))  # even after the hold time has passed
    second = confirm(client, created, name="Someone Else")
    assert second.status_code == 200
    assert second.json() == first.json()
    stored = booking(db_session, created["reference"])
    assert stored.customer_name == "Sam Driver"
    assert stored.confirmed_at == NOW


def test_wrong_token_gives_404(client: TestClient) -> None:
    created = hold(client)
    response = confirm(client, created | {"hold_token": "not-the-token"})
    assert response.status_code == 404
    assert response.json() == {"detail": "Booking not found"}


def test_unknown_reference_gives_the_same_404(client: TestClient) -> None:
    created = hold(client)
    response = confirm(client, created | {"reference": "ZZZZ-ZZZZ"})
    assert response.status_code == 404
    assert response.json() == {"detail": "Booking not found"}


@pytest.mark.parametrize("reference", ["X" * 10, "AB%00CD"], ids=["too-long", "nul"])
def test_odd_references_give_404(client: TestClient, reference: str) -> None:
    created = hold(client)
    assert confirm(client, created | {"reference": reference}).status_code == 404


def test_late_confirm_gives_410_and_releases(client: TestClient, db_session: Session) -> None:
    created = hold(client)
    set_now(client, NOW + timedelta(minutes=5))  # exactly at expiry counts as expired
    response = confirm(client, created)
    assert response.status_code == 410
    assert response.json() == {"detail": "Your hold has expired"}
    released = booking(db_session, created["reference"])
    assert released.status == "expired"
    assert not released.reservation.active


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
def test_field_rules_give_422_naming_the_field(client: TestClient, field: str, value: str) -> None:
    response = confirm(client, hold(client), **{field: value})
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail.startswith(f"{field}: ")
    assert "Value error" not in detail


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


def test_delete_confirmed_gives_409_and_changes_nothing(
    client: TestClient, db_session: Session
) -> None:
    created = hold(client)
    confirm(client, created)
    response = cancel(client, created["reference"], created["hold_token"])
    assert response.status_code == 409
    assert response.json() == {"detail": "This booking is already confirmed"}
    stored = booking(db_session, created["reference"])
    assert stored.status == "confirmed"
    assert stored.reservation.active
