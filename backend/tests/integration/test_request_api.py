"""Asking for a needs-approval service: availability with notice, the hold, and the request."""

from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock import utc_now
from app.models import Booking, EmailLog
from app.seed import seed

NOW = datetime(2026, 11, 9, 9, tzinfo=UTC)  # Monday 09:00 in London (GMT)
TUESDAY_0800 = "2026-11-10T08:00:00+00:00"  # 23 hours ahead: too soon for a request
MONDAY_NEXT = "2026-11-16T09:00:00+00:00"  # a week ahead
DETAILS = {
    "name": "Sam Driver",
    "phone": "07700 900123",
    "email": "sam@example.com",
    "registration": "AB12CDE",
    "make": "Ford",
    "model": "Focus",
    "notes": "Engine light on",
}


def set_now(client: TestClient, now: datetime) -> None:
    cast(FastAPI, client.app).dependency_overrides[utc_now] = lambda: now


@pytest.fixture
def client(api_client: TestClient, db_session: Session) -> TestClient:
    seed(db_session)
    set_now(api_client, NOW)
    return api_client


def hold(client: TestClient, services: list[str], start: str) -> Any:
    return client.post("/api/holds", json={"services": services, "start": start})


def held(client: TestClient, services: list[str] | None = None) -> dict[str, Any]:
    response = hold(client, services or ["diagnostic-check"], MONDAY_NEXT)
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


def send(client: TestClient, created: dict[str, Any], token: str | None = None) -> Any:
    body = {"hold_token": token or created["hold_token"]} | DETAILS
    return client.post(f"/api/holds/{created['reference']}/request", json=body)


def booking(session: Session, reference: str) -> Booking:
    session.expire_all()
    return session.scalars(select(Booking).where(Booking.reference == reference)).one()


def templates(session: Session) -> list[str]:
    return list(session.scalars(select(EmailLog.template).order_by(EmailLog.id)))


def test_availability_for_a_request_starts_a_day_ahead(client: TestClient) -> None:
    body = client.get(
        "/api/availability", params={"services": "diagnostic-check", "date": "2026-11-10"}
    ).json()
    assert body["needs_approval"] is True
    assert body["slots"]
    assert all(slot["start"] >= "2026-11-10T09:00:00+00:00" for slot in body["slots"])


def test_availability_for_an_instant_visit_keeps_the_cutoff(client: TestClient) -> None:
    body = client.get(
        "/api/availability", params={"services": "mot-test", "date": "2026-11-10"}
    ).json()
    assert body["needs_approval"] is False
    assert body["slots"][0]["start"] == TUESDAY_0800


def test_request_needs_a_days_notice(client: TestClient) -> None:
    response = hold(client, ["diagnostic-check"], TUESDAY_0800)
    assert response.status_code == 422
    assert response.json()["detail"] == (
        "Requests need 24 hours' notice — please choose a later time"
    )


def test_mixed_bay_types_are_still_refused(client: TestClient) -> None:
    response = hold(client, ["mot-test", "diagnostic-check"], MONDAY_NEXT)
    assert response.status_code == 422
    assert "book them separately" in response.json()["detail"]


def test_sending_a_request_waits_for_staff(client: TestClient, db_session: Session) -> None:
    created = held(client)
    response = send(client, created)
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "pending_approval"
    saved = booking(db_session, created["reference"])
    assert saved.status == "pending_approval"
    assert saved.hold_expires_at == NOW + timedelta(hours=48)
    assert (saved.customer_name, saved.notes) == ("Sam Driver", "Engine light on")
    assert saved.reservation.active
    assert templates(db_session) == ["request_received"]


def test_request_with_wrong_token_is_not_found(client: TestClient) -> None:
    assert send(client, held(client), token="wrong").status_code == 404  # noqa: S106


def test_request_after_the_hold_ran_out_is_gone(client: TestClient, db_session: Session) -> None:
    created = held(client)
    set_now(client, NOW + timedelta(minutes=6))
    response = send(client, created)
    assert response.status_code == 410
    assert booking(db_session, created["reference"]).status == "expired"
    assert templates(db_session) == []


def test_request_sent_twice_is_refused(client: TestClient) -> None:
    created = held(client)
    assert send(client, created).status_code == 201
    assert send(client, created).status_code == 409


def test_an_instant_visit_cant_be_sent_as_a_request(client: TestClient) -> None:
    created = held(client, ["full-service"])
    response = send(client, created)
    assert response.status_code == 409
    assert response.json()["detail"] == "This visit doesn't need approval"


def test_a_request_cant_go_to_checkout(client: TestClient) -> None:
    created = held(client)
    body = {"hold_token": created["hold_token"]} | DETAILS
    response = client.post(f"/api/holds/{created['reference']}/checkout", json=body)
    assert response.status_code == 409
    assert response.json()["detail"] == "This visit needs approval"
