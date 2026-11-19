"""A customer holds a late slot while an admin saves hours that close earlier: one wins."""

import threading
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from alembic import command
from conftest import alembic_config
from factories import make_staff
from sqlalchemy import Engine, delete, select, update
from sqlalchemy.orm import Session

from app.bookings.service import create_hold
from app.db import make_engine
from app.models import Booking, Reservation, Service, StaffUser, Timetable
from app.models.catalogue import FIRST_TIMETABLE_STARTS
from app.repositories.hours import WeekdayHours
from app.repositories.reservations import SlotUnavailable
from app.seed import seed
from app.settings.hours import HoursClash, create_timetable

LONDON = ZoneInfo("Europe/London")
NOW = datetime(2026, 11, 9, 9, tzinfo=UTC)  # Monday
TUESDAY = date(2026, 11, 10)
# Every one of these ends after 16:00, when the new hours close.
STARTS = [
    datetime(2026, 11, 10, hour, minute, tzinfo=LONDON)
    for hour, minute in ((15, 30), (16, 0), (16, 30), (15, 30), (16, 0))
]
CLOSING_AT_FOUR = {weekday: WeekdayHours(time(8), time(16), ()) for weekday in range(7)}


def hold(
    engine: Engine, start: datetime, barrier: threading.Barrier, outcomes: dict[str, str]
) -> None:
    with Session(engine) as session:
        try:
            mot = session.scalars(select(Service).where(Service.slug == "mot-test")).one()
            barrier.wait(timeout=10)
            create_hold(session, [mot], start, NOW, 10)
            session.commit()
            outcomes["hold"] = "won"
        except SlotUnavailable:
            session.rollback()
            outcomes["hold"] = "lost"
        except Exception as error:  # surfaced by the assertion in the test
            outcomes["hold"] = f"error: {error!r}"


def save_hours(engine: Engine, barrier: threading.Barrier, outcomes: dict[str, str]) -> None:
    with Session(engine) as session:
        try:
            admin = session.scalars(select(StaffUser)).one()
            barrier.wait(timeout=10)
            create_timetable(session, admin, TUESDAY, CLOSING_AT_FOUR, LONDON, NOW)
            session.commit()
            outcomes["hours"] = "won"
        except HoursClash:
            session.rollback()
            outcomes["hours"] = "lost"
        except Exception as error:
            outcomes["hours"] = f"error: {error!r}"


def reset(engine: Engine) -> None:
    """No bookings and only the first timetable, for the next round."""
    with Session(engine) as session:
        session.execute(update(Booking).values(status="cancelled"))
        session.execute(update(Reservation).values(active=False))
        session.execute(delete(Timetable).where(Timetable.starts_on != FIRST_TIMETABLE_STARTS))
        session.commit()


def test_hold_racing_shorter_hours_one_wins(fresh_database_url: str) -> None:
    command.upgrade(alembic_config(fresh_database_url), "head")
    engine = make_engine(fresh_database_url)
    try:
        with Session(engine) as session:
            seed(session)
            make_staff(session, role="admin", email="alex.admin@example.com")
            session.commit()

        for start in STARTS:
            barrier = threading.Barrier(2)
            outcomes: dict[str, str] = {}
            threads = [
                threading.Thread(target=hold, args=(engine, start, barrier, outcomes)),
                threading.Thread(target=save_hours, args=(engine, barrier, outcomes)),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=30)
            assert not any(thread.is_alive() for thread in threads), "a thread hung"
            assert outcomes in (
                {"hold": "won", "hours": "lost"},
                {"hold": "lost", "hours": "won"},
            ), f"{start:%H:%M}: {outcomes}"
            reset(engine)
    finally:
        engine.dispose()
