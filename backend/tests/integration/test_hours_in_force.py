"""Which opening hours apply on a date, and free times following them across a change."""

from datetime import UTC, date, datetime, time
from typing import Any, cast

import pytest
from factories import make_timetable
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.clock import utc_now
from app.models.catalogue import FIRST_TIMETABLE_STARTS
from app.repositories.hours import CLOSED, WeekdayHours, hours_on, timetable_on
from app.seed import seed

DEC_1 = date(2026, 12, 1)  # a Tuesday
# From 1 Dec: Tuesday 09:00–12:00 with no break, and no other days (so closed).
SHORT_TUESDAYS = {1: (time(9), time(12))}
DEMO_WEEKDAY = WeekdayHours(time(8), time(17, 30), ((time(12, 30), time(13)),))


@pytest.fixture
def seeded_session(db_session: Session) -> Session:
    seed(db_session)
    return db_session


def set_now(client: TestClient, now: datetime) -> None:
    cast(FastAPI, client.app).dependency_overrides[utc_now] = lambda: now


def mot_slots(client: TestClient, day: str) -> list[dict[str, Any]]:
    response = client.get("/api/availability", params={"services": ["mot-test"], "date": day})
    assert response.status_code == 200, response.text
    slots: list[dict[str, Any]] = response.json()["slots"]
    return slots


def test_timetable_on_picks_latest_started(seeded_session: Session) -> None:
    make_timetable(seeded_session, DEC_1, SHORT_TUESDAYS)
    assert timetable_on(seeded_session, date(2026, 11, 30)).starts_on == FIRST_TIMETABLE_STARTS
    assert timetable_on(seeded_session, DEC_1).starts_on == DEC_1
    assert timetable_on(seeded_session, date(2027, 6, 1)).starts_on == DEC_1


def test_hours_on_spans_two_timetables(seeded_session: Session) -> None:
    make_timetable(seeded_session, DEC_1, SHORT_TUESDAYS)
    monday_before, tuesday_after, monday_after = date(2026, 11, 30), DEC_1, date(2026, 12, 7)
    hours = hours_on(seeded_session, [monday_before, tuesday_after, monday_after])
    assert hours == {
        monday_before: DEMO_WEEKDAY,
        tuesday_after: WeekdayHours(time(9), time(12), ()),
        monday_after: CLOSED,  # the new timetable has no Monday row
    }


def test_free_times_follow_the_new_timetable(
    api_client: TestClient, seeded_session: Session
) -> None:
    make_timetable(seeded_session, DEC_1, SHORT_TUESDAYS)
    set_now(api_client, datetime(2026, 11, 9, 9, tzinfo=UTC))
    before = mot_slots(api_client, "2026-11-24")  # a Tuesday on the demo hours
    assert before[0]["start"] == "2026-11-24T08:00:00+00:00"
    after = [slot["start"][11:16] for slot in mot_slots(api_client, "2026-12-01")]
    assert after == ["09:00", "09:30", "10:00", "10:30", "11:00"]
    assert mot_slots(api_client, "2026-12-07") == []  # Monday, closed from 1 Dec


def test_free_times_switch_timetable_across_clock_change(
    api_client: TestClient, seeded_session: Session
) -> None:
    # The clocks go forward on Sun 29 Mar 2026; the new hours start that same day.
    make_timetable(seeded_session, date(2026, 3, 29), {6: (time(10), time(12))})
    set_now(api_client, datetime(2026, 3, 20, 9, tzinfo=UTC))
    slots = mot_slots(api_client, "2026-03-29")
    assert slots[0]["start"] == "2026-03-29T10:00:00+01:00"  # 09:00Z
    assert [slot["start"][11:16] for slot in slots] == ["10:00", "10:30", "11:00"]
    # The Sunday before, still on the demo hours (10:00–13:00, GMT).
    assert mot_slots(api_client, "2026-03-22")[-1]["start"] == "2026-03-22T12:00:00+00:00"
