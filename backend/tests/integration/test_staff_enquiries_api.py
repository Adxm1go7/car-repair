"""Staff routes for enquiries: the lists, one enquiry, book it in, decline it."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from factories import make_enquiry, make_hold
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock import utc_now
from app.models import Bay, Enquiry
from app.seed import seed

NOW = datetime(2026, 11, 9, 9, tzinfo=UTC)  # Monday 09:00 in London (GMT)
TUESDAY_9 = "2026-11-10T09:00:00+00:00"
TAKEN = "That time has just been taken"


@pytest.fixture
def client(staff_client: TestClient, db_session: Session) -> TestClient:
    seed(db_session)
    staff_client.app.dependency_overrides[utc_now] = lambda: NOW  # type: ignore[attr-defined]
    return staff_client


def mot_bay(session: Session) -> int:
    return session.scalars(select(Bay.id).where(Bay.slug == "mot-bay")).one()


def approval(session: Session, **changes: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "services": ["mot-test"],
        "start": TUESDAY_9,
        "bay_id": mot_bay(session),
        "name": "Sam Driver",
        "phone": "07700 900123",
        "email": "sam@example.com",
        "registration": "AB12CDE",
        "make": "Ford",
        "model": "Focus",
        "notes": "Rattle from the front left when braking",
    }
    values.update(changes)
    return values


def ids(response: Any) -> list[int]:
    assert response.status_code == 200, response.text
    return [row["id"] for row in response.json()]


def test_list_new_oldest_first(client: TestClient, db_session: Session) -> None:
    middle = make_enquiry(db_session, created_at=NOW - timedelta(hours=2))
    oldest = make_enquiry(db_session, created_at=NOW - timedelta(hours=5), name="Old Customer")
    newest = make_enquiry(db_session, created_at=NOW - timedelta(minutes=5))
    make_enquiry(db_session, status="declined", created_at=NOW - timedelta(days=1))
    response = client.get("/api/staff/enquiries")
    assert ids(response) == [oldest.id, middle.id, newest.id]
    first = response.json()[0]
    assert first == {
        "id": oldest.id,
        "status": "new",
        "customer_name": "Old Customer",
        "registration": "AB12CDE",
        "make": "Ford",
        "model": "Focus",
        "summary": "Rattle from the front left when braking",
        "created_at": "2026-11-09T04:00:00+00:00",
        "handled_at": None,
    }
    assert ids(client.get("/api/staff/enquiries?status=new")) == [oldest.id, middle.id, newest.id]


def test_list_summary_is_first_line_cut_to_80(client: TestClient, db_session: Session) -> None:
    make_enquiry(db_session, description="Knocking noise\nonly when cold", created_at=NOW)
    make_enquiry(db_session, description="x" * 200, created_at=NOW + timedelta(seconds=1))
    rows = client.get("/api/staff/enquiries").json()
    assert [row["summary"] for row in rows] == ["Knocking noise", "x" * 80]


def test_list_handled_newest_first(client: TestClient, db_session: Session) -> None:
    def handled(status: str, hours_ago: int) -> Enquiry:
        when = NOW - timedelta(hours=hours_ago)
        return make_enquiry(db_session, status=status, created_at=when - timedelta(days=hours_ago))

    old_decline = handled("declined", 30)
    new_decline = handled("declined", 2)
    old_booked = handled("converted", 40)
    new_booked = handled("converted", 1)
    make_enquiry(db_session)
    assert ids(client.get("/api/staff/enquiries?status=declined")) == [
        new_decline.id,
        old_decline.id,
    ]
    rows = client.get("/api/staff/enquiries?status=converted").json()
    assert [row["id"] for row in rows] == [new_booked.id, old_booked.id]
    assert rows[0]["handled_at"] is not None


def test_list_bad_status(client: TestClient) -> None:
    assert client.get("/api/staff/enquiries?status=open").status_code == 422


def test_detail(client: TestClient, db_session: Session) -> None:
    fresh = make_enquiry(db_session, created_at=NOW)
    body = client.get(f"/api/staff/enquiries/{fresh.id}").json()
    assert body == {
        "id": fresh.id,
        "status": "new",
        "customer_name": "Sam Driver",
        "customer_phone": "07700 900123",
        "customer_email": "sam@example.com",
        "registration": "AB12CDE",
        "make": "Ford",
        "model": "Focus",
        "description": "Rattle from the front left when braking",
        "created_at": "2026-11-09T09:00:00+00:00",
        "handled_at": None,
        "handled_by": None,
        "decline_reason": None,
        "booking_reference": None,
        "actions": ["approve", "decline"],
    }
    booked = make_enquiry(db_session, status="converted", created_at=NOW)
    body = client.get(f"/api/staff/enquiries/{booked.id}").json()
    assert body["actions"] == []
    assert booked.booking is not None
    assert body["booking_reference"] == booked.booking.reference
    assert body["handled_by"] == "Sam Staff"
    missing = client.get("/api/staff/enquiries/999999")
    assert (missing.status_code, missing.json()) == (404, {"detail": "No such enquiry"})


def test_approve_route(client: TestClient, db_session: Session) -> None:
    enquiry = make_enquiry(db_session)
    response = client.post(f"/api/staff/enquiries/{enquiry.id}/approve", json=approval(db_session))
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["status"], body["actions"]) == ("converted", [])
    reference = body["booking_reference"]
    booking = client.get(f"/api/staff/bookings/{reference}").json()
    assert (booking["status"], booking["source"]) == ("confirmed", "enquiry")
    assert booking["deposit_status"] == "not_required"
    assert booking["enquiry_id"] == enquiry.id
    assert [entry["text"] for entry in booking["history"]] == [
        "Booked from an enquiry by Sam Staff"
    ]


def test_phone_booking_has_no_enquiry(client: TestClient, db_session: Session) -> None:
    body = approval(db_session)
    response = client.post("/api/staff/bookings", json=body)
    reference = response.json()["reference"]
    booking = client.get(f"/api/staff/bookings/{reference}").json()
    assert booking["enquiry_id"] is None
    assert booking["history"][0]["text"] == "Booked by phone by Sam Staff"


def test_approve_needs_email(client: TestClient, db_session: Session) -> None:
    enquiry = make_enquiry(db_session)
    response = client.post(
        f"/api/staff/enquiries/{enquiry.id}/approve", json=approval(db_session, email="  ")
    )
    assert response.status_code == 422
    assert response.json()["detail"].startswith("email:")


def test_approve_mixed_services_refused(client: TestClient, db_session: Session) -> None:
    enquiry = make_enquiry(db_session)
    response = client.post(
        f"/api/staff/enquiries/{enquiry.id}/approve",
        json=approval(db_session, services=["mot-test", "full-service"]),
    )
    assert response.status_code == 422
    db_session.refresh(enquiry)
    assert enquiry.status == "new"


def test_approve_taken_returns_409(client: TestClient, db_session: Session) -> None:
    make_hold(db_session, datetime.fromisoformat(TUESDAY_9), NOW, status="confirmed")
    enquiry = make_enquiry(db_session)
    db_session.commit()
    response = client.post(f"/api/staff/enquiries/{enquiry.id}/approve", json=approval(db_session))
    assert (response.status_code, response.json()) == (409, {"detail": TAKEN})
    db_session.refresh(enquiry)
    assert enquiry.status == "new"


def test_approve_and_decline_not_new(client: TestClient, db_session: Session) -> None:
    declined = make_enquiry(db_session, status="declined", created_at=NOW)
    for action, body in (("approve", approval(db_session)), ("decline", {})):
        response = client.post(f"/api/staff/enquiries/{declined.id}/{action}", json=body)
        assert (response.status_code, response.json()) == (409, {"detail": "not_new"})


def test_unknown_enquiry_actions_404(client: TestClient, db_session: Session) -> None:
    for action, body in (("approve", approval(db_session)), ("decline", {})):
        response = client.post(f"/api/staff/enquiries/999999/{action}", json=body)
        assert response.status_code == 404


def test_decline_route(client: TestClient, db_session: Session) -> None:
    enquiry = make_enquiry(db_session)
    response = client.post(
        f"/api/staff/enquiries/{enquiry.id}/decline", json={"reason": " Too busy this month "}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["status"], body["decline_reason"]) == ("declined", "Too busy this month")
    assert (body["handled_by"], body["handled_at"]) == ("Sam Staff", "2026-11-09T09:00:00+00:00")
    assert body["actions"] == []
