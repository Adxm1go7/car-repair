"""Admins read the audit log: newest first, 50 a page, filtered by date, person or booking."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from factories import make_staff
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import StaffUser
from app.seed import seed
from app.staff.audit import record_audit

T0 = datetime(2026, 11, 10, 9, tzinfo=UTC)


@pytest.fixture
def admin(admin_client: TestClient, db_session: Session) -> StaffUser:
    seed(db_session)
    return db_session.scalars(select(StaffUser).where(StaffUser.role == "admin")).one()


def entry(
    session: Session, who: StaffUser | None, at: datetime, reference: str | None = None
) -> None:
    record_audit(
        session,
        who,
        "booking.status",
        "booking",
        1,
        before={"status": "confirmed"},
        after={"status": "in_progress"},
        reason="Because",
        booking_reference=reference,
        now=at,
    )


def audit(client: TestClient, **params: Any) -> dict[str, Any]:
    response = client.get("/api/staff/audit", params=params)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def test_audit_is_newest_first_50_a_page(
    admin_client: TestClient, db_session: Session, admin: StaffUser
) -> None:
    for n in range(55):
        entry(db_session, admin, T0 + timedelta(minutes=n))
    first = audit(admin_client)
    assert len(first["entries"]) == 50
    assert first["has_more"] is True
    assert first["page"] == 1
    assert first["entries"][0]["at"] == "2026-11-10T09:54:00+00:00"
    assert first["entries"][0] == {
        "at": "2026-11-10T09:54:00+00:00",
        "staff_name": "Alex Admin",
        "action": "booking.status",
        "entity_type": "booking",
        "entity_id": 1,
        "booking_reference": None,
        "before": {"status": "confirmed"},
        "after": {"status": "in_progress"},
        "reason": "Because",
    }
    second = audit(admin_client, page=2)
    assert len(second["entries"]) == 5
    assert second["has_more"] is False
    assert second["entries"][-1]["at"] == "2026-11-10T09:00:00+00:00"


def test_audit_filters_by_staff_reference_and_dates(
    admin_client: TestClient, db_session: Session, admin: StaffUser
) -> None:
    other = make_staff(db_session)
    entry(db_session, admin, T0, "AAAA-AAAA")
    entry(db_session, other, T0 + timedelta(days=1), "BBBB-BBBB")
    entry(db_session, other, T0 + timedelta(days=2), "AAAA-AAAA")

    def refs(**params: Any) -> list[str]:
        return [e["booking_reference"] for e in audit(admin_client, **params)["entries"]]

    assert refs(staff=other.id) == ["AAAA-AAAA", "BBBB-BBBB"]
    assert refs(reference="aaaa-aaaa") == ["AAAA-AAAA", "AAAA-AAAA"]
    assert refs(**{"from": "2026-11-11"}) == ["AAAA-AAAA", "BBBB-BBBB"]
    assert refs(to="2026-11-11") == ["BBBB-BBBB", "AAAA-AAAA"]
    assert refs(**{"from": "2026-11-11", "to": "2026-11-11"}) == ["BBBB-BBBB"]


def test_dates_are_garage_local(
    admin_client: TestClient, db_session: Session, admin: StaffUser
) -> None:
    # 23:30 UTC on 31 March 2027 is 00:30 on 1 April in London.
    entry(db_session, admin, datetime(2027, 3, 31, 23, 30, tzinfo=UTC), "LATE-LATE")
    refs = [
        e["booking_reference"] for e in audit(admin_client, **{"from": "2027-04-01"})["entries"]
    ]
    assert refs == ["LATE-LATE"]


def test_setup_entries_show_setup(
    admin_client: TestClient, db_session: Session, admin: StaffUser
) -> None:
    entry(db_session, None, T0)
    assert audit(admin_client)["entries"][0]["staff_name"] == "Setup"


def test_bad_page_is_422(admin_client: TestClient, admin: StaffUser) -> None:
    assert admin_client.get("/api/staff/audit", params={"page": 0}).status_code == 422


def test_staff_cannot_read_the_audit_log(staff_client: TestClient) -> None:
    assert staff_client.get("/api/staff/audit").status_code == 403
