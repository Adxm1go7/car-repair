"""Staff book a customer who phoned: confirmed at once, no deposit, email optional."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.clock import utc_now
from app.email.reminders import queue_due_reminders
from app.models import AuditEntry, Bay, Booking, EmailLog, StaffUser
from app.seed import seed

NOW = datetime(2026, 11, 9, 9, tzinfo=UTC)  # Monday 09:00
TUESDAY_9 = "2026-11-10T09:00:00+00:00"


@pytest.fixture
def client(staff_client: TestClient, db_session: Session) -> TestClient:
    seed(db_session)
    staff_client.app.dependency_overrides[utc_now] = lambda: NOW  # type: ignore[attr-defined]
    return staff_client


def bay(session: Session, slug: str) -> int:
    return session.scalars(select(Bay.id).where(Bay.slug == slug)).one()


def body(session: Session, **changes: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "services": ["mot-test"],
        "start": TUESDAY_9,
        "bay_id": bay(session, "mot-bay"),
        "name": "Pat Caller",
        "phone": "07700 900456",
        "email": "pat@example.com",
        "registration": "cd34 efg",
        "make": "Vauxhall",
        "model": "Corsa",
        "notes": "Rang at 8",
    }
    values.update(changes)
    return values


def book(client: TestClient, session: Session, **changes: Any) -> Booking:
    response = client.post("/api/staff/bookings", json=body(session, **changes))
    assert response.status_code == 201, response.text
    reference = response.json()["reference"]
    return session.scalars(select(Booking).where(Booking.reference == reference)).one()


def emails(session: Session) -> list[str]:
    return list(session.scalars(select(EmailLog.template).order_by(EmailLog.id)))


def test_phone_booking_with_email_is_confirmed_and_emailed(
    client: TestClient, db_session: Session
) -> None:
    booking = book(client, db_session)
    staff = db_session.scalars(select(StaffUser)).one()
    assert (booking.status, booking.source, booking.deposit_status) == (
        "confirmed",
        "phone",
        "not_required",
    )
    assert booking.created_by == staff.id
    assert booking.confirmed_at == NOW
    assert booking.car_registration == "CD34EFG"
    assert [item.service_name for item in booking.items] == ["MOT test"]
    assert booking.reservation.bay_id == bay(db_session, "mot-bay")
    assert emails(db_session) == ["confirmation"]
    entry = db_session.scalars(select(AuditEntry)).one()
    assert (entry.action, entry.booking_reference, entry.staff_user_id) == (
        "booking.create",
        booking.reference,
        staff.id,
    )


@pytest.mark.parametrize("email", [None, "", "  "])
def test_phone_booking_without_email_queues_nothing(
    client: TestClient, db_session: Session, email: str | None
) -> None:
    booking = book(client, db_session, email=email)
    assert booking.customer_email is None
    assert emails(db_session) == []


def test_phone_booking_bad_email_is_422(client: TestClient, db_session: Session) -> None:
    response = client.post("/api/staff/bookings", json=body(db_session, email="not an email"))
    assert response.status_code == 422


def test_phone_booking_into_a_taken_time_is_409(client: TestClient, db_session: Session) -> None:
    book(client, db_session)
    response = client.post("/api/staff/bookings", json=body(db_session, name="Second"))
    assert response.status_code == 409
    assert response.json() == {"detail": "That time has just been taken"}
    assert db_session.scalar(select(func.count()).select_from(Booking)) == 1


def test_phone_booking_in_a_bay_of_the_wrong_type_is_409(
    client: TestClient, db_session: Session
) -> None:
    response = client.post(
        "/api/staff/bookings", json=body(db_session, bay_id=bay(db_session, "bay-1"))
    )
    assert response.status_code == 409


def test_phone_booking_allows_needs_approval_service(
    client: TestClient, db_session: Session
) -> None:
    booking = book(
        client,
        db_session,
        services=["clutch-replacement"],
        bay_id=bay(db_session, "bay-2"),
    )
    assert booking.status == "confirmed"


def test_phone_booking_mixed_bay_types_is_422(client: TestClient, db_session: Session) -> None:
    response = client.post(
        "/api/staff/bookings", json=body(db_session, services=["mot-test", "full-service"])
    )
    assert response.status_code == 422


def test_phone_booking_inside_the_cutoff_is_allowed(
    client: TestClient, db_session: Session
) -> None:
    booking = book(client, db_session, start="2026-11-09T09:30:00+00:00")  # 30 minutes away
    assert booking.status == "confirmed"


def test_phone_booking_in_the_past_is_422(client: TestClient, db_session: Session) -> None:
    response = client.post(
        "/api/staff/bookings", json=body(db_session, start="2026-11-09T08:00:00+00:00")
    )
    assert response.status_code == 422


def test_phone_booking_without_email_survives_move_cancel_and_reminders(
    client: TestClient, db_session: Session
) -> None:
    booking = book(client, db_session, email=None)
    booking.confirmed_at = NOW - timedelta(days=5)  # booked well before the reminder window
    db_session.flush()
    assert queue_due_reminders(db_session, booking.start_at - timedelta(hours=47), 48) == 0
    assert emails(db_session) == []
