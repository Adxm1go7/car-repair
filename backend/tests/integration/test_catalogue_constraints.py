"""The database itself must reject bad catalogue rows, not just the app code."""

import uuid
from datetime import date, time
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import BayType, OpeningHours, OpeningHoursBreak, Service, Timetable
from app.models.catalogue import FIRST_TIMETABLE_STARTS


def make_service(session: Session, **overrides: Any) -> Service:
    """A valid service on a fresh bay type; each test overrides one field to make it invalid."""
    bay_type = BayType(slug=f"type-{uuid.uuid4().hex[:8]}", name="Test bay type")
    session.add(bay_type)
    session.flush()
    fields: dict[str, Any] = {
        "slug": f"service-{uuid.uuid4().hex[:8]}",
        "name": "Test service",
        "category": "Testing",
        "description": "A service used in tests.",
        "duration_minutes": 60,
        "price_from_pence": 1000,
        "price_to_pence": None,
        "required_bay_type_id": bay_type.id,
        "approval_mode": "instant",
        "sort_order": 0,
    }
    fields.update(overrides)
    return Service(**fields)


def make_timetable(session: Session, starts_on: date = FIRST_TIMETABLE_STARTS) -> Timetable:
    timetable = Timetable(starts_on=starts_on)
    session.add(timetable)
    session.flush()
    return timetable


def day(
    timetable: Timetable, weekday: int, open_time: time | None, close_time: time | None
) -> OpeningHours:
    return OpeningHours(
        timetable_id=timetable.id, weekday=weekday, open_time=open_time, close_time=close_time
    )


def assert_rejected(session: Session, *rows: object) -> None:
    """Insert rows inside a savepoint and expect the database to refuse them."""
    with pytest.raises(IntegrityError), session.begin_nested():
        session.add_all(rows)
        session.flush()


def test_valid_service_and_closed_day_are_accepted(db_session: Session) -> None:
    db_session.add(make_service(db_session, price_from_pence=45000, price_to_pence=75000))
    db_session.add(day(make_timetable(db_session), 6, None, None))
    db_session.flush()


def test_service_duration_must_be_positive(db_session: Session) -> None:
    assert_rejected(db_session, make_service(db_session, duration_minutes=0))


def test_service_price_cannot_be_negative(db_session: Session) -> None:
    assert_rejected(db_session, make_service(db_session, price_from_pence=-1))


def test_service_price_range_top_cannot_be_below_bottom(db_session: Session) -> None:
    service = make_service(db_session, price_from_pence=500, price_to_pence=400)
    assert_rejected(db_session, service)


def test_service_approval_mode_must_be_known(db_session: Session) -> None:
    assert_rejected(db_session, make_service(db_session, approval_mode="maybe"))


def test_service_slug_must_be_unique(db_session: Session) -> None:
    db_session.add(make_service(db_session, slug="mot-test"))
    db_session.flush()
    assert_rejected(db_session, make_service(db_session, slug="mot-test"))


def test_opening_hours_weekday_must_be_0_to_6(db_session: Session) -> None:
    assert_rejected(db_session, day(make_timetable(db_session), 7, time(8), time(17)))


def test_opening_hours_open_and_close_set_together(db_session: Session) -> None:
    assert_rejected(db_session, day(make_timetable(db_session), 0, time(8), None))


def test_opening_hours_open_before_close(db_session: Session) -> None:
    assert_rejected(db_session, day(make_timetable(db_session), 0, time(17), time(8)))


def test_break_must_end_after_it_starts(db_session: Session) -> None:
    timetable = make_timetable(db_session)
    db_session.add(day(timetable, 0, time(8), time(17, 30)))
    db_session.flush()
    bad_break = OpeningHoursBreak(
        timetable_id=timetable.id, weekday=0, start_time=time(13), end_time=time(12, 30)
    )
    assert_rejected(db_session, bad_break)


def test_timetable_start_is_unique(db_session: Session) -> None:
    make_timetable(db_session, date(2026, 12, 1))
    assert_rejected(db_session, Timetable(starts_on=date(2026, 12, 1)))


def test_break_must_belong_to_a_day_of_its_timetable(db_session: Session) -> None:
    timetable = make_timetable(db_session)
    orphan = OpeningHoursBreak(
        timetable_id=timetable.id, weekday=3, start_time=time(12), end_time=time(13)
    )
    assert_rejected(db_session, orphan)


def test_deleting_a_timetable_deletes_its_days_and_breaks(db_session: Session) -> None:
    timetable = make_timetable(db_session, date(2026, 12, 1))
    db_session.add(day(timetable, 0, time(8), time(17)))
    db_session.flush()
    db_session.add(
        OpeningHoursBreak(
            timetable_id=timetable.id, weekday=0, start_time=time(12), end_time=time(13)
        )
    )
    db_session.flush()
    db_session.delete(timetable)
    db_session.flush()
    assert db_session.scalar(select(func.count()).select_from(OpeningHours)) == 0
    assert db_session.scalar(select(func.count()).select_from(OpeningHoursBreak)) == 0
