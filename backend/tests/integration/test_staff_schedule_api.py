"""The staff schedule: bays, each day's hours, and the bookings and blocks in range."""

from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import pytest
from factories import make_block_reservation, make_hold, make_timetable
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock import utc_now
from app.models import Bay
from app.seed import seed

NOW = datetime(2026, 11, 9, 9, tzinfo=UTC)  # Monday
TUESDAY = "2026-11-10"


@pytest.fixture
def client(staff_client: TestClient, db_session: Session) -> TestClient:
    seed(db_session)
    staff_client.app.dependency_overrides[utc_now] = lambda: NOW  # type: ignore[attr-defined]
    return staff_client


def bay(session: Session, slug: str) -> int:
    return session.scalars(select(Bay.id).where(Bay.slug == slug)).one()


def utc(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=UTC)


def schedule(client: TestClient, start: str = TUESDAY, days: int = 1) -> dict[str, Any]:
    response = client.get("/api/staff/schedule", params={"from": start, "days": days})
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def test_schedule_lists_bookings_and_blocks_per_bay(
    client: TestClient, db_session: Session
) -> None:
    booking = make_hold(db_session, utc(10, 9), NOW, status="confirmed")
    make_block_reservation(db_session, bay(db_session, "bay-1"), utc(10, 14), utc(10, 15))
    body = schedule(client)
    assert [b["slug"] for b in body["bays"]] == ["mot-bay", "bay-1", "bay-2", "bay-3"]
    assert body["timezone"] == "Europe/London"
    items = {item["kind"]: item for item in body["items"]}
    assert items["booking"] == {
        "kind": "booking",
        "bay_id": bay(db_session, "mot-bay"),
        "start": "2026-11-10T09:00:00+00:00",
        "end": "2026-11-10T10:00:00+00:00",  # the real end, without the buffer
        "reference": booking.reference,
        "status": "confirmed",
        "registration": "AB12CDE",
        "services": [],
        "source": "online",
        "has_email": True,
        "block_id": None,
        "note": None,
    }
    assert items["block"]["bay_id"] == bay(db_session, "bay-1")
    assert items["block"]["note"] == "Blocked"
    assert items["block"]["start"] == "2026-11-10T14:00:00+00:00"


def test_schedule_leaves_out_cancelled_and_expired(client: TestClient, db_session: Session) -> None:
    make_hold(db_session, utc(10, 9), NOW, status="cancelled", details=True)
    make_hold(db_session, utc(10, 11), NOW - timedelta(minutes=1))  # a hold past its time
    make_block_reservation(
        db_session, bay(db_session, "bay-1"), utc(10, 14), utc(10, 15), active=False
    )
    assert schedule(client)["items"] == []


def test_schedule_shows_held_as_held(client: TestClient, db_session: Session) -> None:
    make_hold(db_session, utc(10, 9), NOW + timedelta(minutes=5))
    (item,) = schedule(client)["items"]
    assert item["status"] == "held"
    assert item["registration"] is None


def test_schedule_leaves_out_other_days(client: TestClient, db_session: Session) -> None:
    make_hold(db_session, utc(11, 9), NOW, status="confirmed")
    assert schedule(client)["items"] == []
    assert len(schedule(client, days=2)["items"]) == 1


def test_schedule_week_has_seven_days_with_hours(client: TestClient) -> None:
    days = schedule(client, "2026-11-09", 7)["days"]
    assert [d["date"] for d in days] == [f"2026-11-{n:02d}" for n in range(9, 16)]
    assert days[0] == {
        "date": "2026-11-09",
        "open": "08:00",
        "close": "17:30",
        "breaks": [{"start": "12:30", "end": "13:00"}],
    }
    assert days[5] == {"date": "2026-11-14", "open": "09:00", "close": "14:00", "breaks": []}


def test_schedule_times_are_local_across_clock_change(
    client: TestClient, db_session: Session
) -> None:
    make_hold(db_session, datetime(2027, 3, 28, 9, tzinfo=UTC), NOW, status="confirmed")
    (item,) = schedule(client, "2027-03-28")["items"]
    assert item["start"] == "2027-03-28T10:00:00+01:00"


@pytest.mark.parametrize("days", [0, 8])
def test_schedule_days_out_of_range_is_422(client: TestClient, days: int) -> None:
    response = client.get("/api/staff/schedule", params={"from": TUESDAY, "days": days})
    assert response.status_code == 422


def test_schedule_bad_date_is_422(client: TestClient) -> None:
    assert client.get("/api/staff/schedule", params={"from": "tuesday"}).status_code == 422


# --- availability --------------------------------------------------------------


def availability(client: TestClient, *services: str, day: str = TUESDAY) -> dict[str, Any]:
    response = client.get("/api/staff/availability", params={"services": services, "date": day})
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def test_staff_availability_lists_bays_for_each_start(
    client: TestClient, db_session: Session
) -> None:
    first = availability(client, "full-service")["slots"][0]
    general = [bay(db_session, slug) for slug in ("bay-1", "bay-2", "bay-3")]
    assert first == {
        "start": "2026-11-10T08:00:00+00:00",
        "end": first["end"],
        "bay_ids": general,
    }


def test_staff_availability_allows_needs_approval_service(client: TestClient) -> None:
    assert availability(client, "clutch-replacement")["slots"]


def test_staff_availability_is_inside_the_cutoff(client: TestClient) -> None:
    starts = [
        s["start"][11:16] for s in availability(client, "mot-test", day="2026-11-09")["slots"]
    ]
    assert starts[0] == "09:00"  # now is 09:00; customers' 2-hour cut-off doesn't apply


def test_staff_availability_ignores_the_window(client: TestClient) -> None:
    assert availability(client, "mot-test", day="2027-03-02")["slots"]


def test_staff_availability_mixed_bay_types(client: TestClient) -> None:
    body = availability(client, "mot-test", "full-service")
    assert body["unavailable_reason"] == "mixed_bay_types"
    assert body["slots"] == []


def test_staff_availability_unknown_service_is_422(client: TestClient) -> None:
    response = client.get("/api/staff/availability", params={"services": ["nope"], "date": TUESDAY})
    assert response.status_code == 422


def test_schedule_days_follow_timetables(client: TestClient, db_session: Session) -> None:
    # From Tue 1 Dec: Tuesday 09:00–12:00, every other day closed.
    make_timetable(db_session, date(2026, 12, 1), {1: (time(9), time(12))})
    days = schedule(client, "2026-11-30", 3)["days"]
    assert days[0] == {
        "date": "2026-11-30",
        "open": "08:00",
        "close": "17:30",
        "breaks": [{"start": "12:30", "end": "13:00"}],
    }
    assert days[1] == {"date": "2026-12-01", "open": "09:00", "close": "12:00", "breaks": []}
    assert days[2] == {"date": "2026-12-02", "open": None, "close": None, "breaks": []}


def test_schedule_shows_out_of_use_bay_only_on_days_with_items(
    client: TestClient, db_session: Session
) -> None:
    bay_1, bay_2 = db_session.get(Bay, bay(db_session, "bay-1")), bay(db_session, "bay-2")
    assert bay_1 is not None
    make_block_reservation(db_session, bay_1.id, utc(10, 14), utc(10, 15))
    bay_1.active = False
    db_session.flush()
    shown = {b["slug"]: b["active"] for b in schedule(client)["bays"]}
    assert shown == {"mot-bay": True, "bay-1": False, "bay-2": True, "bay-3": True}
    assert "bay-1" not in {b["slug"] for b in schedule(client, start="2026-11-11")["bays"]}
    week = schedule(client, start=TUESDAY, days=7)["bays"]
    assert [b["slug"] for b in week] == ["mot-bay", "bay-1", "bay-2", "bay-3"]
    assert bay_2 in {b["id"] for b in week}
