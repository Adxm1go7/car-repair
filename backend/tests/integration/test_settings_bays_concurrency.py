"""A customer holds a slot in a bay while an admin takes that bay out of use: one wins."""

import threading
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from alembic import command
from conftest import alembic_config
from factories import make_staff
from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from app.bookings.service import create_hold
from app.db import make_engine
from app.models import Bay, Booking, Reservation, Service, StaffUser
from app.repositories.reservations import SlotUnavailable
from app.seed import seed
from app.settings.bays import BayInUse, update_bay

LONDON = ZoneInfo("Europe/London")
NOW = datetime(2026, 11, 9, 9, tzinfo=UTC)
# The MOT bay is the only bay of its type, so taking it out leaves the hold nowhere to go.
STARTS = [
    datetime(2026, 11, 10, hour, minute, tzinfo=LONDON)
    for hour, minute in ((8, 0), (9, 30), (11, 0), (13, 0), (14, 30))
]


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


def take_out(engine: Engine, barrier: threading.Barrier, outcomes: dict[str, str]) -> None:
    with Session(engine) as session:
        try:
            admin = session.scalars(select(StaffUser)).one()
            bay = session.scalars(select(Bay).where(Bay.slug == "mot-bay")).one()
            barrier.wait(timeout=10)
            update_bay(session, admin, bay, {"active": False}, NOW)
            session.commit()
            outcomes["out"] = "won"
        except BayInUse:
            session.rollback()
            outcomes["out"] = "lost"
        except Exception as error:
            outcomes["out"] = f"error: {error!r}"


def reset(engine: Engine) -> None:
    """Back to an empty MOT bay in use, for the next round."""
    with Session(engine) as session:
        session.execute(update(Booking).values(status="cancelled"))
        session.execute(update(Reservation).values(active=False))
        session.execute(update(Bay).values(active=True))
        session.commit()


def test_hold_racing_out_of_use_one_wins(fresh_database_url: str) -> None:
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
                threading.Thread(target=take_out, args=(engine, barrier, outcomes)),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=30)
            assert not any(thread.is_alive() for thread in threads), "a thread hung"
            assert outcomes in ({"hold": "won", "out": "lost"}, {"hold": "lost", "out": "won"}), (
                f"{start:%H:%M}: {outcomes}"
            )
            reset(engine)
    finally:
        engine.dispose()
