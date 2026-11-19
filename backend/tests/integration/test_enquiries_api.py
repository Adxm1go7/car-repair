"""A customer sends an enquiry: no login, no slot, no payment; one "received" email."""

from datetime import UTC, datetime
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock import utc_now
from app.models import EmailLog, Enquiry
from app.seed import seed

NOW = datetime(2026, 11, 19, 9, tzinfo=UTC)
DETAILS: dict[str, Any] = {
    "name": "  Sam Driver ",
    "phone": "07700 900123",
    "email": "Sam@Example.com",
    "registration": "ab12 cde",
    "make": "Ford",
    "model": "Focus",
    "description": "  Rattle from the front left when braking  ",
}


@pytest.fixture
def client(api_client: TestClient, db_session: Session) -> TestClient:
    seed(db_session)
    cast(FastAPI, api_client.app).dependency_overrides[utc_now] = lambda: NOW
    return api_client


def stored(session: Session) -> list[Enquiry]:
    return list(session.scalars(select(Enquiry)))


def test_send_enquiry(client: TestClient, db_session: Session) -> None:
    response = client.post("/api/enquiries", json=DETAILS)
    assert response.status_code == 201
    assert response.json() == {"email": "sam@example.com"}
    (enquiry,) = stored(db_session)
    assert enquiry.status == "new"
    assert enquiry.created_at == NOW
    assert (enquiry.customer_name, enquiry.customer_email) == ("Sam Driver", "sam@example.com")
    assert enquiry.car_registration == "AB12CDE"
    assert enquiry.description == "Rattle from the front left when braking"
    (email,) = db_session.scalars(select(EmailLog))
    assert (email.template, email.enquiry_id) == ("enquiry_received", enquiry.id)


def test_send_enquiry_missing_description(client: TestClient, db_session: Session) -> None:
    body = {key: value for key, value in DETAILS.items() if key != "description"}
    response = client.post("/api/enquiries", json=body)
    assert response.status_code == 422
    assert response.json()["detail"].startswith("description:")
    assert stored(db_session) == []


def test_send_enquiry_short_description(client: TestClient, db_session: Session) -> None:
    response = client.post("/api/enquiries", json={**DETAILS, "description": "noise"})
    assert response.status_code == 422
    assert response.json() == {
        "detail": "description: Please describe the problem in at least 10 characters"
    }
    assert stored(db_session) == []


def test_send_enquiry_bad_email(client: TestClient, db_session: Session) -> None:
    response = client.post("/api/enquiries", json={**DETAILS, "email": "not-an-email"})
    assert response.status_code == 422
    assert response.json() == {"detail": "email: Please enter a valid email address"}
    assert db_session.scalars(select(EmailLog)).first() is None


def test_send_enquiry_needs_no_login_or_origin(client: TestClient) -> None:
    client.cookies.clear()
    response = client.post("/api/enquiries", json=DETAILS, headers={"Origin": "https://evil.test"})
    assert response.status_code == 201
