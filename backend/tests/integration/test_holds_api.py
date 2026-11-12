"""POST /api/holds against the seeded demo garage."""

from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.bookings import service as booking_service
from app.bookings.rules import hash_token
from app.clock import utc_now
from app.models import Booking, Setting
from app.seed import seed

NOW = datetime(2026, 11, 9, 9, tzinfo=UTC)  # Monday 09:00 in London (GMT)
MOT_0800 = "2026-11-10T08:00:00+00:00"  # Tuesday; local time equals UTC in November


def set_now(client: TestClient, now: datetime) -> None:
    cast(FastAPI, client.app).dependency_overrides[utc_now] = lambda: now


def hold(client: TestClient, services: list[str], start: str) -> Any:  # an HTTP response
    return client.post("/api/holds", json={"services": services, "start": start})


def mot_starts(client: TestClient, day: str = "2026-11-10") -> list[str]:
    response = client.get("/api/availability", params={"services": "mot-test", "date": day})
    assert response.status_code == 200
    return [slot["start"] for slot in response.json()["slots"]]


def booking(session: Session, reference: str) -> Booking:
    session.expire_all()
    return session.scalars(select(Booking).where(Booking.reference == reference)).one()


@pytest.fixture
def client(api_client: TestClient, db_session: Session) -> TestClient:
    seed(db_session)
    set_now(api_client, NOW)
    return api_client


# --- success ---------------------------------------------------------------------


def test_hold_returns_201_with_the_design_shape(client: TestClient) -> None:
    response = hold(client, ["mot-test"], MOT_0800)
    assert response.status_code == 201
    body = response.json()
    assert body["start"] == MOT_0800
    assert body["end"] == "2026-11-10T09:00:00+00:00"
    assert body["expires_at"] == "2026-11-09T09:10:00+00:00"
    assert body["expires_in_seconds"] == 600
    assert body["services"] == [
        {
            "slug": "mot-test",
            "name": "MOT test",
            "duration_minutes": 60,
            "price_from_pence": 5485,
            "price_to_pence": None,
        }
    ]
    assert len(body["hold_token"]) >= 40
    assert len(body["reference"]) == 9


def test_hold_stores_snapshots_and_hashes_the_token(
    client: TestClient, db_session: Session
) -> None:
    body = hold(client, ["oil-filter-change", "air-con-regas"], MOT_0800).json()
    stored = booking(db_session, body["reference"])
    assert stored.status == "held"
    assert stored.hold_token_hash == hash_token(body["hold_token"])
    assert stored.hold_token_hash != body["hold_token"]
    assert stored.reservation.active
    assert [(i.position, i.service_name, i.duration_minutes) for i in stored.items] == [
        (0, "Oil & filter change", 45),
        (1, "Air-con regas", 60),
    ]
    assert body["end"] == "2026-11-10T09:45:00+00:00"  # 45 + 60 minutes


def test_hold_takes_the_slot_out_of_availability(client: TestClient) -> None:
    assert MOT_0800 in mot_starts(client)
    hold(client, ["mot-test"], MOT_0800)
    assert MOT_0800 not in mot_starts(client)


def test_a_reference_clash_is_retried(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    taken = hold(client, ["mot-test"], MOT_0800).json()["reference"]
    references = iter([taken, "ZZZZ-ZZZZ"])
    monkeypatch.setattr(booking_service, "new_reference", lambda: next(references))
    response = hold(client, ["mot-test"], "2026-11-10T10:00:00+00:00")
    assert response.status_code == 201
    assert response.json()["reference"] == "ZZZZ-ZZZZ"


# --- refusals --------------------------------------------------------------------


def test_taken_slot_gives_409(client: TestClient) -> None:
    assert hold(client, ["mot-test"], MOT_0800).status_code == 201
    response = hold(client, ["mot-test"], MOT_0800)
    assert response.status_code == 409
    assert response.json() == {"detail": "That time has just been taken"}


def test_off_grid_start_gives_409(client: TestClient) -> None:
    assert hold(client, ["mot-test"], "2026-11-10T08:10:00+00:00").status_code == 409


def test_mixed_bay_types_gives_422(client: TestClient) -> None:
    response = hold(client, ["mot-test", "full-service"], MOT_0800)
    assert response.status_code == 422
    assert "book them separately" in response.json()["detail"]


def test_needs_approval_service_gives_422(client: TestClient) -> None:
    response = hold(client, ["diagnostic-check"], MOT_0800)
    assert response.status_code == 422
    assert "needs approval" in response.json()["detail"]


def test_start_without_offset_gives_422(client: TestClient) -> None:
    response = hold(client, ["mot-test"], "2026-11-10T08:00:00")
    assert response.status_code == 422
    assert response.json()["detail"].startswith("start: ")


@pytest.mark.parametrize(
    "services",
    [[], ["no-such-service"], ["mot-test", "mot-test"], ["mot-test"] * 21, [""]],
    ids=["empty", "unknown", "duplicate", "too-many", "blank"],
)
def test_service_validation_matches_availability(client: TestClient, services: list[str]) -> None:
    response = hold(client, services, MOT_0800)
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], str)


@pytest.mark.parametrize(
    "start",
    ["2026-11-08T08:00:00+00:00", "2027-01-09T09:00:00+00:00"],
    ids=["yesterday", "day-after-window"],
)
def test_past_and_beyond_window_dates_give_422(client: TestClient, start: str) -> None:
    assert hold(client, ["mot-test"], start).status_code == 422


def test_broken_hold_setting_gives_503(client: TestClient, db_session: Session) -> None:
    setting = db_session.get(Setting, "slot_hold_minutes")
    assert setting is not None
    setting.value = 0
    db_session.flush()
    assert hold(client, ["mot-test"], MOT_0800).status_code == 503


# --- expiry ----------------------------------------------------------------------


def test_expired_hold_is_freed_on_the_spot(client: TestClient, db_session: Session) -> None:
    first = hold(client, ["mot-test"], MOT_0800).json()
    set_now(client, NOW + timedelta(minutes=10, seconds=1))
    assert MOT_0800 in mot_starts(client)  # before anything has released it
    assert hold(client, ["mot-test"], MOT_0800).status_code == 201
    released = booking(db_session, first["reference"])
    assert released.status == "expired"
    assert not released.reservation.active
