from unittest.mock import ANY

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import OpeningHours, Service, Setting
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


def test_opening_hours_returns_seven_days_with_breaks(
    api_client: TestClient, db_session: Session
) -> None:
    seed(db_session)
    body = api_client.get("/api/opening-hours").json()
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
    wednesday = db_session.get(OpeningHours, 2)
    assert wednesday is not None
    db_session.delete(wednesday)
    db_session.flush()
    body = api_client.get("/api/opening-hours").json()
    assert len(body) == 7
    assert body[2] == {"weekday": 2, "open": None, "close": None, "breaks": []}


# --- /api/garage ----------------------------------------------------------------


def test_garage_returns_contact_and_timezone(api_client: TestClient, db_session: Session) -> None:
    seed(db_session)
    assert api_client.get("/api/garage").json() == {
        "name": "Hillside Motors",
        "address": "12 Station Road, Anytown, AT1 2CD",
        "phone": "01632 960123",
        "email": "bookings@example.com",
        "timezone": "Europe/London",
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
