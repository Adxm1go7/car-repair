"""The public form routes refuse a visitor over the limit with a 429; other routes, other
actions and other visitors are not affected."""

from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from factories import make_hold
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import limits
from app.clock import utc_now
from app.limits import Action
from app.models import Booking, EmailLog, Enquiry
from app.seed import seed

NOW = datetime(2026, 11, 9, 9, tzinfo=UTC)  # Monday 09:00 in London (GMT)
MOT_0800 = "2026-11-10T08:00:00+00:00"
TOO_MANY = "Too many attempts. Please wait a few minutes and try again."
ENQUIRY: dict[str, Any] = {
    "name": "Sam Driver",
    "phone": "07700 900123",
    "email": "sam@example.com",
    "registration": "AB12CDE",
    "make": "Ford",
    "model": "Focus",
    "description": "Rattle from the front left when braking",
}
# Each limited route, with a body. The limit is checked before the body, so an empty body
# still counts as an attempt (a 422) and then gets the 429.
ROUTES: list[tuple[Action, str]] = [
    ("hold", "/api/holds"),
    ("pay", "/api/holds/ABCD-EFGH/checkout"),
    ("pay", "/api/bookings/ABCD-EFGH/pay"),
    ("request", "/api/holds/ABCD-EFGH/request"),
    ("enquiry", "/api/enquiries"),
    ("link", "/api/bookings/ABCD-EFGH/cancel"),
]


@pytest.fixture
def client(api_client: TestClient, db_session: Session) -> TestClient:
    seed(db_session)
    cast(FastAPI, api_client.app).dependency_overrides[utc_now] = lambda: NOW
    return api_client


def limit(monkeypatch: pytest.MonkeyPatch, action: Action, count: int) -> None:
    monkeypatch.setitem(limits.LIMITS, action, (count, timedelta(minutes=15)))


def bookings(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(Booking)) or 0


@pytest.mark.parametrize(("action", "path"), ROUTES)
def test_each_action_is_limited(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, action: Action, path: str
) -> None:
    limit(monkeypatch, action, 2)
    for _ in range(2):
        assert client.post(path, json={}).status_code != 429
    refused = client.post(path, json={})
    assert refused.status_code == 429
    assert refused.json() == {"detail": TOO_MANY}
    assert int(refused.headers["Retry-After"]) >= 1


def test_refused_hold_creates_nothing(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    limit(monkeypatch, "hold", 1)
    assert (
        client.post("/api/holds", json={"services": ["mot-test"], "start": MOT_0800}).status_code
        == 201
    )
    later = "2026-11-10T09:30:00+00:00"
    refused = client.post("/api/holds", json={"services": ["mot-test"], "start": later})
    assert refused.status_code == 429
    assert bookings(db_session) == 1


def test_refused_enquiry_stores_nothing(client: TestClient, db_session: Session) -> None:
    for _ in range(5):
        assert client.post("/api/enquiries", json=ENQUIRY).status_code == 201
    assert client.post("/api/enquiries", json=ENQUIRY).status_code == 429
    assert db_session.scalar(select(func.count()).select_from(Enquiry)) == 5
    emails = (
        select(func.count()).select_from(EmailLog).where(EmailLog.template == "enquiry_received")
    )
    assert db_session.scalar(emails) == 5


def test_failed_attempt_still_counts(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_hold(db_session, datetime.fromisoformat(MOT_0800), NOW, status="confirmed")
    db_session.commit()
    limit(monkeypatch, "hold", 2)
    body = {"services": ["mot-test"], "start": MOT_0800}
    assert [client.post("/api/holds", json=body).status_code for _ in range(2)] == [409, 409]
    assert client.post("/api/holds", json=body).status_code == 429


def test_limits_are_per_action_and_ip(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    limit(monkeypatch, "enquiry", 1)
    assert client.post("/api/enquiries", json=ENQUIRY).status_code == 201
    assert client.post("/api/enquiries", json=ENQUIRY).status_code == 429
    # Another action from the same visitor still works.
    hold = client.post("/api/holds", json={"services": ["mot-test"], "start": MOT_0800})
    assert hold.status_code == 201
    # Another visitor can still send an enquiry.
    other = TestClient(client.app, client=("198.51.100.9", 50000))
    assert other.post("/api/enquiries", json=ENQUIRY).status_code == 201


def test_unlimited_routes(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    for action in limits.LIMITS:
        limit(monkeypatch, action, 1)
    for path in ("/api/holds/ABCD-EFGH/status", "/api/bookings/ABCD-EFGH/view"):
        for _ in range(5):
            assert client.post(path, json={"hold_token": "x", "token": "x"}).status_code != 429
    for _ in range(5):
        response = client.request("DELETE", "/api/holds/ABCD-EFGH", json={"hold_token": "x"})
        assert response.status_code != 429
