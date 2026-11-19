"""Admins add, edit and delete future opening-hours timetables; clashing changes are refused."""

from datetime import UTC, date, datetime, time
from typing import Any

import pytest
from factories import make_hold, make_timetable
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.clock import utc_now
from app.models import AuditEntry, Timetable
from app.seed import seed

NOW = datetime(2026, 11, 9, 9, tzinfo=UTC)  # Monday 9 Nov; London is on UTC in November
URL = "/api/staff/settings/hours"
WEEKDAY = (time(8), time(17, 30))


@pytest.fixture
def client(admin_client: TestClient, db_session: Session) -> TestClient:
    seed(db_session)
    admin_client.app.dependency_overrides[utc_now] = lambda: NOW  # type: ignore[attr-defined]
    return admin_client


def utc(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=UTC)


def week(**changes: dict[str, Any]) -> list[dict[str, Any]]:
    """The seed's week as request days; `changes` keyed "d0".."d6" replace parts of a day."""
    days: list[dict[str, Any]] = []
    for weekday in range(7):
        if weekday < 5:
            day = {
                "open": "08:00",
                "close": "17:30",
                "breaks": [{"start": "12:30", "end": "13:00"}],
            }
        elif weekday == 5:
            day = {"open": "09:00", "close": "14:00", "breaks": []}
        else:
            day = {"open": "10:00", "close": "13:00", "breaks": []}
        days.append({"weekday": weekday, **day, **changes.get(f"d{weekday}", {})})
    return days


CLOSED: dict[str, Any] = {"open": None, "close": None, "breaks": []}


def add(client: TestClient, starts_on: str, days: list[dict[str, Any]]) -> Any:
    return client.post(URL, json={"starts_on": starts_on, "days": days})


def timetable_count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(Timetable)) or 0


def audit_actions(session: Session) -> list[str]:
    return list(session.scalars(select(AuditEntry.action).order_by(AuditEntry.id)))


def test_list_marks_past_current_future(client: TestClient, db_session: Session) -> None:
    make_timetable(db_session, date(2026, 10, 1), {0: WEEKDAY})
    make_timetable(db_session, date(2026, 12, 1), {0: WEEKDAY})
    body = client.get(URL).json()
    assert [(t["starts_on"], t["state"]) for t in body] == [
        ("2000-01-01", "past"),
        ("2026-10-01", "current"),
        ("2026-12-01", "future"),
    ]
    assert body[0]["days"][0] == {
        "weekday": 0,
        "open": "08:00",
        "close": "17:30",
        "breaks": [{"start": "12:30", "end": "13:00"}],
    }
    assert body[2]["days"][1] == {"weekday": 1, "open": None, "close": None, "breaks": []}
    assert all(isinstance(t["id"], int) for t in body)


def test_add_from_tomorrow(client: TestClient, db_session: Session) -> None:
    response = add(client, "2026-11-10", week(d1={"close": "16:00"}))
    assert response.status_code == 201
    created = response.json()
    assert (created["starts_on"], created["state"]) == ("2026-11-10", "future")
    assert created["days"][1]["close"] == "16:00"
    public = client.get("/api/opening-hours").json()["timetables"]
    assert [t["starts_on"] for t in public] == ["2000-01-01", "2026-11-10"]


def test_add_today_is_422(client: TestClient, db_session: Session) -> None:
    for day in ("2026-11-09", "2026-01-01"):
        response = add(client, day, week())
        assert response.status_code == 422
        assert response.json() == {"detail": "New hours can start tomorrow at the earliest"}
    assert timetable_count(db_session) == 1


def test_add_on_a_taken_date_is_422(client: TestClient, db_session: Session) -> None:
    assert add(client, "2026-12-01", week()).status_code == 201
    response = add(client, "2026-12-01", week())
    assert response.status_code == 422
    assert response.json() == {"detail": "There are already hours from that date"}


@pytest.mark.parametrize(
    "change",
    [
        {"d1": CLOSED},  # closed that day
        {"d1": {"close": "09:30", "breaks": []}},  # closes before it ends
        {"d1": {"breaks": [{"start": "09:30", "end": "10:00"}]}},  # a new break over it
        {"d1": {"open": "09:30"}},  # opens after it starts
    ],
)
def test_add_refused_when_a_booking_falls_outside(
    client: TestClient, db_session: Session, change: dict[str, Any]
) -> None:
    booking = make_hold(db_session, utc(10, 9), NOW, status="confirmed")  # Tue 09:00–10:00
    response = add(client, "2026-11-10", week(**change))
    assert response.status_code == 409
    assert response.json() == {
        "detail": "clashes",
        "bookings": [
            {
                "reference": booking.reference,
                "start": "2026-11-10T09:00:00+00:00",
                "bay": "MOT bay",
                "held": False,
            }
        ],
    }
    assert timetable_count(db_session) == 1
    assert audit_actions(db_session) == []


def test_add_ignores_bookings_after_the_next_timetable(
    client: TestClient, db_session: Session
) -> None:
    make_timetable(db_session, date(2026, 11, 17), {d: WEEKDAY for d in range(7)})
    make_hold(db_session, utc(17, 9), NOW, status="confirmed")  # under the 17 Nov hours
    response = add(client, "2026-11-10", week(d1=CLOSED))
    assert response.status_code == 201


def test_add_ignores_bookings_that_do_not_count(client: TestClient, db_session: Session) -> None:
    make_hold(db_session, utc(10, 9), NOW, status="cancelled")
    make_hold(db_session, utc(10, 11), utc(9, 8, 59))  # a hold past its time
    assert add(client, "2026-11-10", week(d1=CLOSED)).status_code == 201


def test_edit_future_refused_on_clash(client: TestClient, db_session: Session) -> None:
    created = add(client, "2026-11-10", week()).json()
    booking = make_hold(db_session, utc(10, 9), NOW, status="confirmed")
    refused = client.put(f"{URL}/{created['id']}", json={"days": week(d1=CLOSED)})
    assert refused.status_code == 409
    assert [b["reference"] for b in refused.json()["bookings"]] == [booking.reference]
    saved = client.get(URL).json()[-1]
    assert saved["days"][1]["open"] == "08:00"
    edited = client.put(f"{URL}/{created['id']}", json={"days": week(d1={"close": "16:00"})})
    assert edited.status_code == 200
    assert edited.json()["days"][1]["close"] == "16:00"
    assert edited.json()["days"][1]["breaks"] == [{"start": "12:30", "end": "13:00"}]
    assert client.get(URL).json()[-1] == edited.json()


def test_edit_current_is_409(client: TestClient, db_session: Session) -> None:
    current = make_timetable(db_session, date(2026, 11, 9), {0: WEEKDAY})
    first = client.get(URL).json()[0]
    for timetable_id in (current.id, first["id"]):
        response = client.put(f"{URL}/{timetable_id}", json={"days": week()})
        assert response.status_code == 409
        assert response.json() == {"detail": "not_allowed"}
        assert client.delete(f"{URL}/{timetable_id}").status_code == 409
    assert client.put(f"{URL}/999999", json={"days": week()}).status_code == 404
    assert client.delete(f"{URL}/999999").status_code == 404


def test_delete_future(client: TestClient, db_session: Session) -> None:
    created = add(client, "2026-12-01", week(d0=CLOSED)).json()
    response = client.delete(f"{URL}/{created['id']}")
    assert response.status_code == 204
    assert timetable_count(db_session) == 1


def test_delete_refused_when_previous_hours_clash(client: TestClient, db_session: Session) -> None:
    created = add(client, "2026-12-01", week(d1={"close": "19:00"})).json()
    booking = make_hold(db_session, datetime(2026, 12, 1, 18, tzinfo=UTC), NOW, status="confirmed")
    response = client.delete(f"{URL}/{created['id']}")
    assert response.status_code == 409
    assert [b["reference"] for b in response.json()["bookings"]] == [booking.reference]
    assert timetable_count(db_session) == 2


@pytest.mark.parametrize(
    "days",
    [
        week(d0={"breaks": [{"start": "07:30", "end": "08:30"}]}),  # starts before opening
        week(d0={"breaks": [{"start": "17:00", "end": "18:00"}]}),  # ends after closing
        week(d0={"breaks": [{"start": "13:00", "end": "12:30"}]}),  # backwards
        week(
            d0={"breaks": [{"start": "12:00", "end": "13:00"}, {"start": "12:30", "end": "14:00"}]}
        ),
        week(d0={"open": None, "close": None, "breaks": [{"start": "12:00", "end": "13:00"}]}),
        week(d0={"open": "09:00", "close": None}),
        week(d0={"open": "17:00", "close": "09:00"}),
        week(d0={"open": "09:00", "close": "09:00"}),
        week()[:6],  # six days
        [*week()[:6], {**week()[0], "weekday": 0}],  # Monday twice, no Sunday
        [*week()[:6], {**week()[6], "weekday": 7}],
        week(d0={"open": "8am"}),
    ],
)
def test_breaks_outside_hours_or_overlapping_are_422(
    client: TestClient, db_session: Session, days: list[dict[str, Any]]
) -> None:
    assert add(client, "2026-12-01", days).status_code == 422
    assert timetable_count(db_session) == 1


def test_touching_breaks_are_allowed(client: TestClient) -> None:
    breaks = [{"start": "12:00", "end": "12:30"}, {"start": "12:30", "end": "13:00"}]
    assert add(client, "2026-12-01", week(d0={"breaks": breaks})).status_code == 201


def test_hours_changes_are_audited(client: TestClient, db_session: Session) -> None:
    created = add(client, "2026-12-01", week()).json()
    client.put(f"{URL}/{created['id']}", json={"days": week(d6=CLOSED)})
    client.delete(f"{URL}/{created['id']}")
    entries = list(db_session.scalars(select(AuditEntry).order_by(AuditEntry.id)))
    assert [(e.action, e.entity_type, e.entity_id) for e in entries] == [
        ("hours.create", "timetable", created["id"]),
        ("hours.update", "timetable", created["id"]),
        ("hours.delete", "timetable", created["id"]),
    ]
    create, update, delete = entries
    assert create.before is None and create.after is not None
    assert create.after["starts_on"] == "2026-12-01"
    assert len(create.after["days"]) == 7
    assert create.after["days"][0] == {
        "weekday": 0,
        "open": "08:00",
        "close": "17:30",
        "breaks": [{"start": "12:30", "end": "13:00"}],
    }
    assert update.before == create.after
    assert update.after is not None and update.after["days"][6] == {"weekday": 6, **CLOSED}
    assert delete.before == update.after and delete.after is None
