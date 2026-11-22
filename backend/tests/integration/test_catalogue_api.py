from datetime import UTC, date, datetime, time
from typing import Any, cast
from unittest.mock import ANY

from conftest import ClientFor
from factories import first_day, make_timetable
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock import utc_now
from app.config import AppConfig
from app.models import Service, Setting
from app.seed import seed

# --- /api/services --------------------------------------------------------------


def test_services_lists_seeded_services_in_order(
    api_client: TestClient, db_session: Session
) -> None:
    seed(db_session)
    body = api_client.get("/api/services").json()
    assert len(body) == 10
    assert [s["slug"] for s in body][:2] == ["mot-test", "oil-filter-change"]
    assert body[0] == {
        "slug": "mot-test",
        "name": "MOT test",
        "category": "MOT",
        "description": ANY,
        "duration_minutes": 60,
        "price_from_pence": 5485,
        "price_to_pence": None,
        "approval_mode": "instant",
    }


def test_services_hides_inactive_services(api_client: TestClient, db_session: Session) -> None:
    seed(db_session)
    db_session.scalars(select(Service).where(Service.slug == "full-service")).one().active = False
    db_session.flush()
    slugs = [s["slug"] for s in api_client.get("/api/services").json()]
    assert "full-service" not in slugs
    assert len(slugs) == 9


def test_services_does_not_expose_bay_details(api_client: TestClient, db_session: Session) -> None:
    seed(db_session)
    for service in api_client.get("/api/services").json():
        assert not any("bay" in key for key in service)


# --- /api/opening-hours ---------------------------------------------------------


def opening_hours(client: TestClient, now: datetime) -> list[dict[str, Any]]:
    """The timetables listed at `now`."""
    cast(FastAPI, client.app).dependency_overrides[utc_now] = lambda: now
    response = client.get("/api/opening-hours")
    assert response.status_code == 200, response.text
    timetables: list[dict[str, Any]] = response.json()["timetables"]
    return timetables


NOV_9 = datetime(2026, 11, 9, 9, tzinfo=UTC)  # the booking window (60 days) ends 8 Jan 2027


def test_opening_hours_returns_seven_days_with_breaks(
    api_client: TestClient, db_session: Session
) -> None:
    seed(db_session)
    (only,) = opening_hours(api_client, NOV_9)
    assert only["starts_on"] == "2000-01-01"
    body = only["days"]
    assert [d["weekday"] for d in body] == [0, 1, 2, 3, 4, 5, 6]
    assert body[0] == {
        "weekday": 0,
        "open": "08:00",
        "close": "17:30",
        "breaks": [{"start": "12:30", "end": "13:00"}],
    }
    assert body[6] == {"weekday": 6, "open": "10:00", "close": "13:00", "breaks": []}


def test_opening_hours_shows_missing_day_as_closed(
    api_client: TestClient, db_session: Session
) -> None:
    seed(db_session)
    wednesday = first_day(db_session, 2)
    assert wednesday is not None
    db_session.delete(wednesday)
    db_session.flush()
    body = opening_hours(api_client, NOV_9)[0]["days"]
    assert len(body) == 7
    assert body[2] == {"weekday": 2, "open": None, "close": None, "breaks": []}


def test_opening_hours_lists_current_and_upcoming_timetables(
    api_client: TestClient, db_session: Session
) -> None:
    seed(db_session)
    make_timetable(db_session, date(2026, 12, 1), {1: (time(9), time(12))})
    timetables = opening_hours(api_client, NOV_9)
    assert [t["starts_on"] for t in timetables] == ["2000-01-01", "2026-12-01"]
    upcoming = timetables[1]["days"]
    assert upcoming[1] == {"weekday": 1, "open": "09:00", "close": "12:00", "breaks": []}
    assert upcoming[0] == {"weekday": 0, "open": None, "close": None, "breaks": []}
    # Once 1 Dec has come, it's the one in force, and the old week isn't listed.
    after = opening_hours(api_client, datetime(2026, 12, 5, 9, tzinfo=UTC))
    assert [t["starts_on"] for t in after] == ["2026-12-01"]


def test_opening_hours_omits_timetables_beyond_the_window(
    api_client: TestClient, db_session: Session
) -> None:
    seed(db_session)
    make_timetable(db_session, date(2027, 1, 8), {0: (time(8), time(12))})  # last window day
    make_timetable(db_session, date(2027, 1, 9), {0: (time(8), time(13))})  # one day past it
    timetables = opening_hours(api_client, NOV_9)
    assert [t["starts_on"] for t in timetables] == ["2000-01-01", "2027-01-08"]


# --- /api/garage ----------------------------------------------------------------


def test_garage_returns_contact_and_timezone(api_client: TestClient, db_session: Session) -> None:
    seed(db_session)
    assert api_client.get("/api/garage").json() == {
        "name": "Hillside Motors",
        "address": "12 Station Road, Anytown, AT1 2CD",
        "phone": "01632 960123",
        "email": "bookings@example.com",
        "timezone": "Europe/London",
        "demo_site": False,
    }


def test_garage_returns_503_when_settings_missing(api_client: TestClient) -> None:
    response = api_client.get("/api/garage")
    assert response.status_code == 503
    assert response.json() == {"detail": "Garage details unavailable"}


def test_garage_returns_503_when_contact_is_malformed(
    api_client: TestClient, db_session: Session
) -> None:
    seed(db_session)
    contact = db_session.get(Setting, "garage_contact")
    assert contact is not None
    contact.value = {"name": "x"}
    db_session.flush()
    response = api_client.get("/api/garage")
    assert response.status_code == 503
    assert response.json() == {"detail": "Garage details unavailable"}


def test_garage_says_when_it_is_the_demo_site(
    db_session: Session, client_for: ClientFor, migrated_url: str
) -> None:
    seed(db_session)
    config = AppConfig(database_url=migrated_url, environment="test", demo_site=True)
    with client_for(config) as client:
        assert client.get("/api/garage").json()["demo_site"] is True
