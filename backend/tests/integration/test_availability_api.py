"""GET /api/availability against the seeded demo garage."""

from datetime import UTC, datetime, time, timedelta
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.orm import Session

from app.clock import utc_now
from app.models import Bay, OpeningHours, Reservation, Service, Setting
from app.seed import seed

NOW = datetime(2026, 11, 9, 9, tzinfo=UTC)  # Monday 09:00 in London (GMT)
DAY = "2026-11-10"  # a Tuesday
DELETE = object()


def set_now(client: TestClient, now: datetime) -> None:
    cast(FastAPI, client.app).dependency_overrides[utc_now] = lambda: now


def get(client: TestClient, *services: str, day: str = DAY) -> Any:  # an HTTP response
    params = {"services": list(services), "date": day}
    return client.get("/api/availability", params=params)


def utc(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, 10, hour, minute, tzinfo=UTC)


def starts(body: dict[str, Any]) -> list[str]:
    return [slot["start"][11:16] for slot in body["slots"]]


@pytest.fixture
def client(api_client: TestClient, db_session: Session) -> TestClient:
    seed(db_session)
    set_now(api_client, NOW)
    return api_client


# --- shape and content -------------------------------------------------------------


def test_mot_returns_slots_in_local_time(client: TestClient) -> None:
    response = get(client, "mot-test")
    assert response.status_code == 200
    body = response.json()
    assert body["date"] == DAY
    assert body["timezone"] == "Europe/London"
    assert body["duration_minutes"] == 60
    assert body["unavailable_reason"] is None
    assert len(body["slots"]) == 17
    assert body["slots"][0] == {
        "start": "2026-11-10T08:00:00+00:00",
        "end": "2026-11-10T09:00:00+00:00",
    }
    assert "bay" not in response.text


def test_summer_date_has_bst_offset(client: TestClient) -> None:
    set_now(client, datetime(2026, 7, 1, 8, tzinfo=UTC))
    body = get(client, "mot-test", day="2026-07-02").json()
    assert body["slots"][0]["start"] == "2026-07-02T08:00:00+01:00"


def test_multi_service_sums_durations(client: TestClient) -> None:
    body = get(client, "full-service", "front-brake-pads").json()
    assert body["duration_minutes"] == 270
    assert len(body["slots"]) == 10
    assert body["slots"][0] == {
        "start": "2026-11-10T08:00:00+00:00",
        "end": "2026-11-10T12:30:00+00:00",
    }
    assert starts(body)[-1] == "13:00"


def test_mixed_bay_types(client: TestClient) -> None:
    response = get(client, "mot-test", "full-service")
    assert response.status_code == 200
    assert response.json()["slots"] == []
    assert response.json()["unavailable_reason"] == "mixed_bay_types"


def test_closed_day_has_no_slots(client: TestClient, db_session: Session) -> None:
    tuesday = db_session.get(OpeningHours, 1)
    assert tuesday is not None
    tuesday.open_time = tuesday.close_time = None
    db_session.flush()
    body = get(client, "mot-test").json()
    assert body["slots"] == []
    assert body["unavailable_reason"] is None


def test_existing_reservation_removes_slots(client: TestClient, db_session: Session) -> None:
    mot_bay = db_session.scalars(select(Bay.id).where(Bay.slug == "mot-bay")).one()
    db_session.add(Reservation(bay_id=mot_bay, kind="booking", during=Range(utc(8), utc(9, 15))))
    db_session.flush()
    result = starts(get(client, "mot-test").json())
    assert not {"08:00", "08:30", "09:00"} & set(result)
    assert result[0] == "09:30"


def test_buffer_past_midnight_respects_next_days_reservation(
    client: TestClient, db_session: Session
) -> None:
    # Open late on Tuesday; a block starts at midnight. A 22:50 MOT ends 23:50, but its
    # 15-minute buffer runs to 00:05 and would overlap the block, so it mustn't be offered.
    tuesday = db_session.get(OpeningHours, 1)
    assert tuesday is not None
    tuesday.open_time, tuesday.close_time = time(8, 20), time(23, 50)
    mot_bay = db_session.scalars(select(Bay.id).where(Bay.slug == "mot-bay")).one()
    midnight = datetime(2026, 11, 11, tzinfo=UTC)
    db_session.add(
        Reservation(
            bay_id=mot_bay,
            kind="block",
            during=Range(midnight, midnight + timedelta(hours=1)),
        )
    )
    db_session.flush()
    result = starts(get(client, "mot-test").json())
    assert "22:20" in result
    assert "22:50" not in result


def test_needs_approval_services_get_slots(client: TestClient) -> None:
    body = get(client, "clutch-replacement").json()
    assert len(body["slots"]) == 8
    assert body["slots"][0]["end"] == "2026-11-10T14:00:00+00:00"


# --- validation -----------------------------------------------------------------------


def test_missing_services_is_rejected(client: TestClient) -> None:
    assert client.get("/api/availability", params={"date": DAY}).status_code == 422


@pytest.mark.parametrize(
    "services",
    [
        [""],
        ["mot-test", "mot-test"],
        ["no-such-service"],
        ["full-service"],
        ["mot\x00"],
        ["x" * 65],
        [f"service-{n}" for n in range(21)],
    ],
    ids=["empty", "repeated", "unknown", "inactive", "nul-byte", "too-long", "too-many"],
)
def test_rejects_bad_services(client: TestClient, db_session: Session, services: list[str]) -> None:
    full_service = db_session.scalars(select(Service).where(Service.slug == "full-service")).one()
    full_service.active = False
    db_session.flush()
    assert get(client, *services).status_code == 422


@pytest.mark.parametrize("day", ["2026-13-01", "2026-11-08"], ids=["invalid", "yesterday"])
def test_rejects_bad_dates(client: TestClient, day: str) -> None:
    assert get(client, "mot-test", day=day).status_code == 422


@pytest.mark.parametrize(
    ("day", "status"),
    [("2026-11-09", 200), ("2027-01-08", 200), ("2027-01-09", 422)],
    ids=["today", "last-day-of-window", "day-after-window"],
)
def test_window_edges(client: TestClient, day: str, status: int) -> None:
    assert get(client, "mot-test", day=day).status_code == status


def test_today_follows_garage_zone_near_midnight(client: TestClient) -> None:
    set_now(client, datetime(2026, 7, 1, 23, 30, tzinfo=UTC))  # already 00:30 on 2 July in London
    assert get(client, "mot-test", day="2026-07-01").status_code == 422
    assert get(client, "mot-test", day="2026-07-02").status_code == 200


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("slot_grid_minutes", DELETE),
        ("garage_timezone", "Mars/Base"),
        ("booking_window_days", "lots"),
        ("booking_window_days", 10_000_000),
    ],
)
def test_broken_settings_give_503(
    client: TestClient, db_session: Session, key: str, value: Any
) -> None:
    row = db_session.get(Setting, key)
    assert row is not None
    if value is DELETE:
        db_session.delete(row)
    else:
        row.value = value
    db_session.flush()
    response = get(client, "mot-test")
    assert response.status_code == 503
    assert response.json() == {"detail": "Availability unavailable"}
