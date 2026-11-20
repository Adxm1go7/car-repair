"""The hidden `website` field: a bot that fills it gets nowhere; people never notice it."""

import logging
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.clock import utc_now
from app.models import Booking, EmailLog, Enquiry, Payment
from app.seed import seed

NOW = datetime(2026, 11, 9, 9, tzinfo=UTC)  # Monday 09:00 in London (GMT)
MOT_0800 = "2026-11-10T08:00:00+00:00"
MONDAY_NEXT = "2026-11-16T09:00:00+00:00"  # a week ahead: a request needs a day's notice
REFUSED = "Please check your details and try again."
DETAILS: dict[str, Any] = {
    "name": "Sam Bot-Driver",
    "phone": "07700 900123",
    "email": "sam@example.com",
    "registration": "AB12CDE",
    "make": "Ford",
    "model": "Focus",
}
ENQUIRY: dict[str, Any] = DETAILS | {"description": "Rattle from the front left when braking"}


@pytest.fixture
def client(api_client: TestClient, db_session: Session) -> TestClient:
    seed(db_session)
    cast(FastAPI, api_client.app).dependency_overrides[utc_now] = lambda: NOW
    return api_client


def count(session: Session, model: type[Any]) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


def held(client: TestClient, service: str = "mot-test", start: str = MOT_0800) -> dict[str, Any]:
    response = client.post("/api/holds", json={"services": [service], "start": start})
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


def booking(session: Session, reference: str) -> Booking:
    session.expire_all()
    return session.scalars(select(Booking).where(Booking.reference == reference)).one()


def test_enquiry_honeypot_pretends(client: TestClient, db_session: Session) -> None:
    response = client.post("/api/enquiries", json=ENQUIRY | {"website": "http://spam.test"})
    assert (response.status_code, response.json()) == (201, {"email": "sam@example.com"})
    assert count(db_session, Enquiry) == 0
    assert count(db_session, EmailLog) == 0


def test_checkout_honeypot_refused(client: TestClient, db_session: Session) -> None:
    created = held(client)
    body = {"hold_token": created["hold_token"], "website": "spam"} | DETAILS
    response = client.post(f"/api/holds/{created['reference']}/checkout", json=body)
    assert (response.status_code, response.json()) == (422, {"detail": REFUSED})
    hold = booking(db_session, created["reference"])
    assert (hold.status, hold.customer_name) == ("held", None)
    assert count(db_session, Payment) == 0


def test_request_honeypot_refused(client: TestClient, db_session: Session) -> None:
    created = held(client, "diagnostic-check", MONDAY_NEXT)
    body = {"hold_token": created["hold_token"], "website": "spam"} | DETAILS
    response = client.post(f"/api/holds/{created['reference']}/request", json=body)
    assert (response.status_code, response.json()) == (422, {"detail": REFUSED})
    hold = booking(db_session, created["reference"])
    assert (hold.status, hold.customer_name) == ("held", None)
    assert count(db_session, EmailLog) == 0


@pytest.mark.parametrize("website", ["", "   ", None])
def test_empty_honeypot_is_ignored(
    client: TestClient, db_session: Session, website: str | None
) -> None:
    extra = {} if website is None else {"website": website}
    assert client.post("/api/enquiries", json=ENQUIRY | extra).status_code == 201
    assert count(db_session, Enquiry) == 1
    created = held(client)
    body = {"hold_token": created["hold_token"]} | DETAILS | extra
    assert client.post(f"/api/holds/{created['reference']}/checkout", json=body).status_code == 200


def test_honeypot_logs_no_contents(client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        client.post("/api/enquiries", json=ENQUIRY | {"website": "http://spam.test"})
    lines = [r.getMessage() for r in caplog.records if "honeypot" in r.getMessage()]
    assert len(lines) == 1
    assert "/api/enquiries" in lines[0]
    assert "spam.test" not in lines[0]
    assert "Sam Bot-Driver" not in lines[0]
