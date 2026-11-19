"""Admins add and rename bays, take them out of use and back, and add bay types."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from factories import make_block_reservation, make_hold
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock import utc_now
from app.models import AuditEntry, Bay, BayType, Reservation, StaffUser
from app.schedule.blocks import create_block
from app.seed import seed

NOW = datetime(2026, 11, 9, 9, tzinfo=UTC)  # Monday; London is on UTC in November
TUESDAY = "2026-11-10"
BAYS = "/api/staff/settings/bays"
TYPES = "/api/staff/settings/bay-types"


@pytest.fixture
def client(admin_client: TestClient, db_session: Session) -> TestClient:
    seed(db_session)
    admin_client.app.dependency_overrides[utc_now] = lambda: NOW  # type: ignore[attr-defined]
    return admin_client


def utc(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=UTC)


def bay(session: Session, slug: str) -> Bay:
    return session.scalars(select(Bay).where(Bay.slug == slug)).one()


def type_id(session: Session, slug: str) -> int:
    return session.scalars(select(BayType.id).where(BayType.slug == slug)).one()


def add_bay(client: TestClient, session: Session, name: str = "Bay 4") -> dict[str, Any]:
    response = client.post(BAYS, json={"name": name, "bay_type_id": type_id(session, "general")})
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def free_bay_ids(client: TestClient, service: str = "full-service") -> set[int]:
    response = client.get("/api/staff/availability", params={"services": service, "date": TUESDAY})
    assert response.status_code == 200, response.text
    return {bay_id for slot in response.json()["slots"] for bay_id in slot["bay_ids"]}


def audit_actions(session: Session) -> list[str]:
    return list(session.scalars(select(AuditEntry.action).order_by(AuditEntry.id)))


def block_ranges(session: Session, bay_id: int) -> list[tuple[datetime, datetime]]:
    reservations = session.scalars(
        select(Reservation)
        .where(Reservation.bay_id == bay_id, Reservation.kind == "block", Reservation.active)
        .order_by(Reservation.during)
    )
    return [(r.during.lower, r.during.upper) for r in reservations]  # type: ignore[misc]


def admin(session: Session) -> StaffUser:
    return session.scalars(select(StaffUser).where(StaffUser.role == "admin")).one()


def test_add_bay_is_bookable_at_once(client: TestClient, db_session: Session) -> None:
    created = add_bay(client, db_session)
    assert created == {
        "id": created["id"],
        "slug": "bay-4",
        "name": "Bay 4",
        "bay_type_id": type_id(db_session, "general"),
        "bay_type": "General bay",
        "active": True,
    }
    assert created["id"] in free_bay_ids(client)
    assert created in client.get(BAYS).json()


def test_new_bay_slug_is_made_unique(client: TestClient, db_session: Session) -> None:
    bay(db_session, "bay-1").name = "Old bay 1"
    db_session.flush()
    assert add_bay(client, db_session, "Bay 1")["slug"] == "bay-1-2"


def test_rename_bay(client: TestClient, db_session: Session) -> None:
    bay_1 = bay(db_session, "bay-1")
    response = client.patch(f"{BAYS}/{bay_1.id}", json={"name": "  Front bay "})
    assert response.status_code == 200
    assert response.json()["name"] == "Front bay"
    assert response.json()["slug"] == "bay-1"


def test_duplicate_bay_name_is_409(client: TestClient, db_session: Session) -> None:
    body = {"name": "bay 2", "bay_type_id": type_id(db_session, "general")}
    response = client.post(BAYS, json=body)
    assert response.status_code == 409
    assert response.json() == {"detail": "That name is already used"}
    bay_1 = bay(db_session, "bay-1")
    assert client.patch(f"{BAYS}/{bay_1.id}", json={"name": "BAY 2"}).status_code == 409
    assert client.patch(f"{BAYS}/{bay_1.id}", json={"name": "bay 1"}).status_code == 200


def test_bad_bay_fields_are_422(client: TestClient, db_session: Session) -> None:
    general = type_id(db_session, "general")
    for body in [
        {"name": " ", "bay_type_id": general},
        {"name": "x" * 101, "bay_type_id": general},
        {"name": "Bay 9", "bay_type_id": 999_999},
        {"name": "Bay 9"},
    ]:
        assert client.post(BAYS, json=body).status_code == 422, body
    bay_1 = bay(db_session, "bay-1")
    for patch in [{"bay_type_id": general}, {"name": None}, {"active": None}, {"slug": "x"}]:
        assert client.patch(f"{BAYS}/{bay_1.id}", json=patch).status_code == 422, patch
    assert client.patch(f"{BAYS}/999999", json={"active": False}).status_code == 404


def test_out_of_use_refused_with_bookings_listed(client: TestClient, db_session: Session) -> None:
    mot = bay(db_session, "mot-bay")
    later = make_hold(db_session, utc(11, 9), NOW, status="confirmed")
    sooner = make_hold(db_session, utc(10, 9), NOW, status="confirmed")
    make_hold(db_session, utc(5, 9), NOW, status="confirmed")  # already over: not in the way
    response = client.patch(f"{BAYS}/{mot.id}", json={"name": "Renamed", "active": False})
    assert response.status_code == 409
    assert response.json() == {
        "detail": "clashes",
        "bookings": [
            {
                "reference": sooner.reference,
                "start": "2026-11-10T09:00:00+00:00",
                "bay": "MOT bay",
                "held": False,
            },
            {
                "reference": later.reference,
                "start": "2026-11-11T09:00:00+00:00",
                "bay": "MOT bay",
                "held": False,
            },
        ],
    }
    db_session.refresh(mot)
    assert (mot.active, mot.name) == (True, "MOT bay")
    assert audit_actions(db_session) == []


def test_out_of_use_lists_a_hold_as_held(client: TestClient, db_session: Session) -> None:
    mot = bay(db_session, "mot-bay")
    make_hold(db_session, utc(10, 9), NOW + timedelta(minutes=5))
    make_hold(db_session, utc(10, 11), NOW - timedelta(minutes=1))  # past its hold: ignored
    response = client.patch(f"{BAYS}/{mot.id}", json={"active": False})
    assert response.status_code == 409
    assert [b["held"] for b in response.json()["bookings"]] == [True]


def test_out_of_use_with_no_bookings(client: TestClient, db_session: Session) -> None:
    bay_1 = bay(db_session, "bay-1")
    make_block_reservation(db_session, bay_1.id, utc(10, 14), utc(10, 15))  # left alone
    assert bay_1.id in free_bay_ids(client)
    response = client.patch(f"{BAYS}/{bay_1.id}", json={"active": False})
    assert response.status_code == 200
    assert response.json()["active"] is False
    assert bay_1.id not in free_bay_ids(client)
    assert block_ranges(db_session, bay_1.id) == [(utc(10, 14), utc(10, 15))]
    assert bay_1.id in {b["id"] for b in client.get(BAYS).json()}


def test_back_in_use_needs_no_check(client: TestClient, db_session: Session) -> None:
    bay_1 = bay(db_session, "bay-1")
    client.patch(f"{BAYS}/{bay_1.id}", json={"active": False})
    response = client.patch(f"{BAYS}/{bay_1.id}", json={"active": True})
    assert response.status_code == 200
    assert response.json()["active"] is True
    assert bay_1.id in free_bay_ids(client)


def test_new_bay_joins_future_all_bay_blocks(client: TestClient, db_session: Session) -> None:
    me = admin(db_session)
    create_block(db_session, me, None, utc(10, 8), utc(10, 18), "Bank holiday", NOW)
    started = create_block(db_session, me, None, utc(9, 8), utc(9, 12), "Power cut", NOW)
    create_block(db_session, me, None, utc(5, 8), utc(5, 18), "Over already", NOW)
    removed = create_block(db_session, me, None, utc(12, 8), utc(12, 18), "Removed", NOW)
    removed.removed_at = NOW
    one_bay = bay(db_session, "bay-1").id
    create_block(db_session, me, one_bay, utc(11, 8), utc(11, 18), "Just bay 1", NOW)
    created = add_bay(client, db_session)
    # The one under way covers the new bay from now; the others aren't extended.
    assert block_ranges(db_session, created["id"]) == [
        (NOW, utc(9, 12)),
        (utc(10, 8), utc(10, 18)),
    ]
    assert created["id"] not in free_bay_ids(client)  # the bank holiday covers it too
    assert started.end_at == utc(9, 12)


def test_restored_bay_skips_its_own_block_time(client: TestClient, db_session: Session) -> None:
    me = admin(db_session)
    bay_1 = bay(db_session, "bay-1")
    client.patch(f"{BAYS}/{bay_1.id}", json={"active": False})
    own = make_block_reservation(db_session, bay_1.id, utc(10, 10), utc(10, 12))
    create_block(db_session, me, None, utc(10, 8), utc(10, 18), "Bank holiday", NOW)
    assert block_ranges(db_session, bay_1.id) == [(utc(10, 10), utc(10, 12))]
    response = client.patch(f"{BAYS}/{bay_1.id}", json={"active": True})
    assert response.status_code == 200
    assert block_ranges(db_session, bay_1.id) == [
        (utc(10, 8), utc(10, 10)),
        (utc(10, 10), utc(10, 12)),
        (utc(10, 12), utc(10, 18)),
    ]
    assert own.active


def test_add_bay_type_and_cannot_rename(client: TestClient, db_session: Session) -> None:
    response = client.post(TYPES, json={"name": "  Tyre bay "})
    assert response.status_code == 201
    created = response.json()
    assert created == {"id": created["id"], "slug": "tyre-bay", "name": "Tyre bay"}
    assert created in client.get(TYPES).json()
    assert client.post(TYPES, json={"name": "TYRE BAY"}).status_code == 409
    assert client.post(TYPES, json={"name": ""}).status_code == 422
    # There's no route to change a bay type at all.
    assert client.patch(f"{TYPES}/{created['id']}", json={"name": "Tyres"}).status_code == 404
    bay_4 = client.post(BAYS, json={"name": "Tyre bay 1", "bay_type_id": created["id"]})
    assert bay_4.json()["bay_type"] == "Tyre bay"


def test_bay_changes_are_audited(client: TestClient, db_session: Session) -> None:
    client.post(TYPES, json={"name": "Tyre bay"})
    created = add_bay(client, db_session)
    url = f"{BAYS}/{created['id']}"
    client.patch(url, json={"name": "Bay four"})
    client.patch(url, json={"name": "Bay four"})  # no change, no entry
    client.patch(url, json={"active": False})
    client.patch(url, json={"active": True})
    entries = list(db_session.scalars(select(AuditEntry).order_by(AuditEntry.id)))
    assert [(e.action, e.entity_type) for e in entries] == [
        ("bay_type.create", "bay_type"),
        ("bay.create", "bay"),
        ("bay.rename", "bay"),
        ("bay.out_of_use", "bay"),
        ("bay.back_in_use", "bay"),
    ]
    _, create, rename, out, back = entries
    assert create.after == {"slug": "bay-4", "name": "Bay 4", "bay_type": "General bay"}
    assert (rename.before, rename.after) == ({"name": "Bay 4"}, {"name": "Bay four"})
    four = {"name": "Bay four"}
    assert (out.before, out.after) == (four | {"active": True}, four | {"active": False})
    assert (back.before, back.after) == (four | {"active": False}, four | {"active": True})
    assert all(e.entity_id == created["id"] for e in entries[1:])
