"""Staff block time on one bay or every bay. A block can't cover a booking."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from factories import make_hold
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock import utc_now
from app.models import AuditEntry, Bay, Block
from app.seed import seed

NOW = datetime(2026, 11, 9, 9, tzinfo=UTC)  # Monday 09:00


def utc(hour: int, minute: int = 0, day: int = 10) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=UTC)


@pytest.fixture
def client(staff_client: TestClient, db_session: Session) -> TestClient:
    seed(db_session)
    staff_client.app.dependency_overrides[utc_now] = lambda: NOW  # type: ignore[attr-defined]
    return staff_client


def bay(session: Session, slug: str) -> int:
    return session.scalars(select(Bay.id).where(Bay.slug == slug)).one()


def block(
    client: TestClient,
    bay_id: int | None,
    start: datetime,
    end: datetime,
    note: str = "Lift broken",
) -> Any:
    return client.post(
        "/api/staff/blocks",
        json={"bay_id": bay_id, "start": start.isoformat(), "end": end.isoformat(), "note": note},
    )


def mot_starts(client: TestClient) -> list[str]:
    response = client.get(
        "/api/availability", params={"services": "mot-test", "date": "2026-11-10"}
    )
    assert response.status_code == 200, response.text
    return [slot["start"][11:16] for slot in response.json()["slots"]]


def test_block_one_bay(client: TestClient, db_session: Session) -> None:
    response = block(client, bay(db_session, "bay-1"), utc(14), utc(15))
    assert response.status_code == 201, response.text
    saved = db_session.get(Block, response.json()["id"])
    assert saved is not None
    assert (saved.note, saved.all_bays, saved.start_at, saved.end_at) == (
        "Lift broken",
        False,
        utc(14),
        utc(15),
    )
    assert [r.bay_id for r in saved.reservations] == [bay(db_session, "bay-1")]
    assert all(r.kind == "block" and r.active for r in saved.reservations)


def test_block_all_bays_makes_one_reservation_each(client: TestClient, db_session: Session) -> None:
    response = block(client, None, utc(8), utc(17, 30), note="Bank holiday")
    assert response.status_code == 201
    saved = db_session.get(Block, response.json()["id"])
    assert saved is not None
    assert saved.all_bays
    assert len(saved.reservations) == 4


def test_block_over_a_booking_lists_it(client: TestClient, db_session: Session) -> None:
    booking = make_hold(db_session, utc(9), NOW, status="confirmed")
    response = block(client, None, utc(8), utc(12))
    assert response.status_code == 409
    assert response.json() == {
        "detail": "clashes",
        "bookings": [
            {"reference": booking.reference, "start": "2026-11-10T09:00:00+00:00", "bay": "MOT bay"}
        ],
        "blocks": [],
    }
    assert db_session.scalars(select(Block)).all() == []


def test_block_in_a_bookings_buffer_lists_it(client: TestClient, db_session: Session) -> None:
    booking = make_hold(db_session, utc(9), NOW, status="confirmed")  # ends 10:00, buffer 10:15
    response = block(client, bay(db_session, "mot-bay"), utc(10, 5), utc(11))
    assert response.status_code == 409
    assert [b["reference"] for b in response.json()["bookings"]] == [booking.reference]


def test_block_next_to_a_booking_is_fine(client: TestClient, db_session: Session) -> None:
    make_hold(db_session, utc(9), NOW, status="confirmed")
    assert block(client, bay(db_session, "mot-bay"), utc(10, 15), utc(11)).status_code == 201


def test_block_over_a_held_booking_lists_it(client: TestClient, db_session: Session) -> None:
    held = make_hold(db_session, utc(9), NOW + timedelta(minutes=5))
    response = block(client, bay(db_session, "mot-bay"), utc(9), utc(10))
    assert response.status_code == 409
    assert [b["reference"] for b in response.json()["bookings"]] == [held.reference]


def test_block_over_an_expired_hold_is_fine(client: TestClient, db_session: Session) -> None:
    make_hold(db_session, utc(9), NOW - timedelta(minutes=1))
    assert block(client, bay(db_session, "mot-bay"), utc(9), utc(10)).status_code == 201


def test_block_over_another_block_lists_it(client: TestClient, db_session: Session) -> None:
    first = block(client, bay(db_session, "bay-1"), utc(14), utc(15)).json()["id"]
    response = block(client, None, utc(14, 30), utc(16), note="Power cut")
    assert response.status_code == 409
    assert response.json()["blocks"] == [{"id": first, "note": "Lift broken"}]


def test_removed_block_frees_the_time(client: TestClient, db_session: Session) -> None:
    created = block(client, bay(db_session, "mot-bay"), utc(14), utc(15)).json()["id"]
    assert "14:00" not in mot_starts(client)
    assert client.delete(f"/api/staff/blocks/{created}").status_code == 204
    assert "14:00" in mot_starts(client)
    saved = db_session.get(Block, created)
    assert saved is not None
    assert saved.removed_at == NOW
    assert not any(r.active for r in saved.reservations)
    assert client.delete(f"/api/staff/blocks/{created}").status_code == 404


def test_public_availability_skips_blocked_time(client: TestClient, db_session: Session) -> None:
    block(client, bay(db_session, "mot-bay"), utc(14), utc(15))
    found = mot_starts(client)
    assert "13:00" not in found  # ends 14:00, but its 15-minute buffer runs into the block
    assert "14:00" not in found
    assert "14:30" not in found
    assert "15:00" in found


@pytest.mark.parametrize(
    ("start", "end", "note"),
    [
        (utc(15), utc(14), "Backwards"),
        (utc(14), utc(14), "Empty"),
        (utc(14), utc(15), "   "),
        (utc(14), utc(15), "x" * 201),
        (utc(8), utc(8) + timedelta(days=31, minutes=1), "Too long"),
    ],
)
def test_bad_blocks_are_422(
    client: TestClient, db_session: Session, start: datetime, end: datetime, note: str
) -> None:
    assert block(client, bay(db_session, "bay-1"), start, end, note).status_code == 422


def test_unknown_bay_is_422(client: TestClient) -> None:
    assert block(client, 99999, utc(14), utc(15)).status_code == 422


def test_blocks_are_audited(client: TestClient, db_session: Session) -> None:
    created = block(client, bay(db_session, "bay-1"), utc(14), utc(15)).json()["id"]
    client.delete(f"/api/staff/blocks/{created}")
    entries = db_session.scalars(select(AuditEntry).order_by(AuditEntry.id)).all()
    assert [e.action for e in entries] == ["block.create", "block.remove"]
    assert entries[0].after == {
        "bays": ["Bay 1"],
        "start": utc(14).isoformat(),
        "end": utc(15).isoformat(),
        "note": "Lift broken",
    }
    assert entries[1].before == entries[0].after
