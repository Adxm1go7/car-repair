"""Two customers choose the same slot at the same moment: exactly one must win."""

import threading
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from alembic import command
from conftest import alembic_config
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.db import make_engine
from app.models import Reservation, Service
from app.repositories.reservations import SlotUnavailable, reserve
from app.seed import seed

LONDON = ZoneInfo("Europe/London")
NOW = datetime(2026, 11, 9, 9, tzinfo=UTC)
# The MOT bay is the only bay of its type, so both customers really fight over one bay.
# Each round's winner holds the bay for 60 min + 15 min buffer, so starts are 90 min apart.
STARTS = [
    datetime(2026, 11, 10, hour, minute, tzinfo=LONDON)
    for hour, minute in ((8, 0), (9, 30), (11, 0), (13, 0), (14, 30))
]


def attempt(
    engine: Engine,
    service_id: int,
    start: datetime,
    barrier: threading.Barrier,
    outcomes: list[str],
) -> None:
    # Each thread has its own session, so its own database connection and transaction.
    with Session(engine) as session:
        try:
            barrier.wait(timeout=10)
            reserve(session, [service_id], start, NOW)
            session.commit()
            outcomes.append("won")
        except SlotUnavailable:
            session.rollback()
            outcomes.append("lost")
        except Exception as error:  # surfaced by the assertion in the test
            outcomes.append(f"error: {error!r}")


def test_two_simultaneous_reserves_of_one_bay_have_exactly_one_winner(
    fresh_database_url: str,
) -> None:
    command.upgrade(alembic_config(fresh_database_url), "head")
    engine = make_engine(fresh_database_url)
    try:
        with Session(engine) as session:
            seed(session)
            session.commit()  # the threads need committed data on their own connections
            mot_id = session.scalars(select(Service.id).where(Service.slug == "mot-test")).one()

        for start in STARTS:
            barrier = threading.Barrier(2)
            outcomes: list[str] = []
            threads = [
                threading.Thread(target=attempt, args=(engine, mot_id, start, barrier, outcomes))
                for _ in range(2)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=30)
            assert not any(thread.is_alive() for thread in threads), "a reserve hung"
            assert sorted(outcomes) == ["lost", "won"], f"{start:%H:%M}: {outcomes}"

        with Session(engine) as session:
            active = select(func.count()).select_from(Reservation).where(Reservation.active)
            assert session.scalar(active) == len(STARTS)
    finally:
        engine.dispose()
