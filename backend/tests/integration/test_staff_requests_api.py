"""Staff routes for requests: the queue, approve, propose and decline."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from factories import make_hold, make_request
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock import utc_now
from app.models import Bay, Booking
from app.seed import seed

NOW = datetime(2026, 11, 9, 9, tzinfo=UTC)  # Monday 09:00 in London (GMT)
START = datetime(2026, 11, 16, 9, tzinfo=UTC)
LATER = "2026-11-17T10:00:00+00:00"


@pytest.fixture
def client(staff_client: TestClient, db_session: Session) -> TestClient:
    seed(db_session)
    staff_client.app.dependency_overrides[utc_now] = lambda: NOW  # type: ignore[attr-defined]
    return staff_client


def bay(session: Session, slug: str) -> int:
    return session.scalars(select(Bay.id).where(Bay.slug == slug)).one()


def act(client: TestClient, booking: Booking, action: str, body: dict[str, Any]) -> Any:
    return client.post(f"/api/staff/bookings/{booking.reference}/{action}", json=body)


def test_queue_lists_waiting_requests_oldest_first(client: TestClient, db_session: Session) -> None:
    first = make_request(db_session, START, NOW + timedelta(hours=40))
    second = make_request(db_session, START, NOW + timedelta(hours=48), bay_slug="bay-2")
    second.created_at = NOW
    first.created_at = NOW - timedelta(hours=8)
    make_request(db_session, START, NOW - timedelta(minutes=1), bay_slug="bay-3")  # overdue
    make_request(
        db_session, START + timedelta(days=1), NOW + timedelta(hours=24), status="awaiting_deposit"
    )
    db_session.flush()
    response = client.get("/api/staff/requests")
    assert response.status_code == 200
    body = response.json()
    assert [r["reference"] for r in body] == [first.reference, second.reference]
    assert body[0] == {
        "reference": first.reference,
        "customer_name": "Sam Driver",
        "services": ["Diagnostic check"],
        "start": "2026-11-16T09:00:00+00:00",
        "bay": "Bay 1",
        "deadline": "2026-11-11T01:00:00+00:00",
        "created_at": "2026-11-09T01:00:00+00:00",
    }


def test_approve_route(client: TestClient, db_session: Session) -> None:
    booking = make_request(db_session, START, NOW + timedelta(hours=48))
    response = act(client, booking, "approve", {})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "awaiting_deposit"
    assert body["deadline"] == "2026-11-10T09:00:00+00:00"
    assert body["actions"] == ["propose", "cancel"]
    assert body["history"][-1]["text"] == "Approved by Sam Staff"


def test_approve_route_refusals(client: TestClient, db_session: Session) -> None:
    confirmed = make_hold(db_session, START, NOW, status="confirmed")
    assert act(client, confirmed, "approve", {}).json()["detail"] == "not_allowed"
    overdue = make_request(db_session, START, NOW - timedelta(minutes=1), bay_slug="bay-2")
    response = act(client, overdue, "approve", {})
    assert (response.status_code, response.json()["detail"]) == (409, "expired")
    soon = make_request(db_session, NOW + timedelta(hours=3), NOW + timedelta(hours=1))
    assert act(client, soon, "approve", {}).json()["detail"] == "too_soon"


def test_unknown_booking_is_404(client: TestClient) -> None:
    assert client.post("/api/staff/bookings/NONE-0000/approve", json={}).status_code == 404


def test_propose_route(client: TestClient, db_session: Session) -> None:
    booking = make_request(db_session, START, NOW + timedelta(hours=48))
    body = {"start": LATER, "bay_id": bay(db_session, "bay-2"), "reason": "Parts"}
    response = act(client, booking, "propose", body)
    assert response.status_code == 200, response.text
    assert response.json()["start"] == LATER
    assert response.json()["history"][-1]["text"] == 'New time proposed by Sam Staff — "Parts"'


def test_propose_route_refusals(client: TestClient, db_session: Session) -> None:
    booking = make_request(db_session, START, NOW + timedelta(hours=48))
    make_hold(
        db_session,
        datetime(2026, 11, 17, 10, tzinfo=UTC),
        NOW + timedelta(minutes=5),
        bay_slug="bay-2",
    )
    taken = act(client, booking, "propose", {"start": LATER, "bay_id": bay(db_session, "bay-2")})
    assert (taken.status_code, taken.json()["detail"]) == (409, "taken")
    soon = {"start": "2026-11-09T12:00:00+00:00", "bay_id": bay(db_session, "bay-3")}
    assert act(client, booking, "propose", soon).json()["detail"] == "too_soon"


def test_decline_route(client: TestClient, db_session: Session) -> None:
    booking = make_request(db_session, START, NOW + timedelta(hours=48))
    response = act(client, booking, "decline", {"reason": "Not for that model"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "cancelled"
    assert body["history"][-1]["text"] == 'Declined by Sam Staff — "Not for that model"'
