"""Two customers hold the same slot at the same moment: exactly one gets it."""

import threading
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from alembic import command
from conftest import alembic_config
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.bookings.service import create_hold
from app.db import make_engine
from app.models import Booking, Service
from app.repositories.reservations import SlotUnavailable
from app.seed import seed

LONDON = ZoneInfo("Europe/London")
NOW = datetime(2026, 11, 9, 9, tzinfo=UTC)
# The MOT bay is the only bay of its type. Starts are 90 minutes apart (60 + 15 buffer).
STARTS = [
    datetime(2026, 11, 10, hour, minute, tzinfo=LONDON)
    for hour, minute in ((8, 0), (9, 30), (11, 0), (13, 0), (14, 30))
]


def attempt(
    engine: Engine, start: datetime, barrier: threading.Barrier, outcomes: list[str]
) -> None:
    with Session(engine) as session:  # its own connection and transaction
        try:
            mot = session.scalars(select(Service).where(Service.slug == "mot-test")).one()
            barrier.wait(timeout=10)
            create_hold(session, [mot], start, NOW, 10)
            session.commit()
            outcomes.append("won")
        except SlotUnavailable:
            session.rollback()
            outcomes.append("lost")
        except Exception as error:  # surfaced by the assertion in the test
            outcomes.append(f"error: {error!r}")


def test_two_simultaneous_holds_have_exactly_one_winner(fresh_database_url: str) -> None:
    command.upgrade(alembic_config(fresh_database_url), "head")
    engine = make_engine(fresh_database_url)
    try:
        with Session(engine) as session:
            seed(session)
            session.commit()

        for start in STARTS:
            barrier = threading.Barrier(2)
            outcomes: list[str] = []
            threads = [
                threading.Thread(target=attempt, args=(engine, start, barrier, outcomes))
                for _ in range(2)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=30)
            assert sorted(outcomes) == ["lost", "won"], f"at {start}: {outcomes}"

        with Session(engine) as session:
            held = session.scalar(
                select(func.count()).select_from(Booking).where(Booking.status == "held")
            )
            assert held == len(STARTS)
    finally:
        engine.dispose()
