"""The worker releases expired holds and commits, so the API sees the slot as free."""

from datetime import UTC, datetime, timedelta

from alembic import command
from conftest import alembic_config
from factories import make_hold
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import make_engine
from app.models import Booking
from app.seed import seed
from app.worker import run_once

NOW = datetime(2026, 11, 9, 9, tzinfo=UTC)


def test_run_once_releases_and_commits(fresh_database_url: str) -> None:
    command.upgrade(alembic_config(fresh_database_url), "head")
    engine = make_engine(fresh_database_url)
    try:
        with Session(engine) as session:
            seed(session)
            expired = make_hold(
                session, datetime(2026, 11, 10, 8, tzinfo=UTC), NOW - timedelta(minutes=1)
            ).reference
            live = make_hold(
                session, datetime(2026, 11, 10, 10, tzinfo=UTC), NOW + timedelta(minutes=5)
            ).reference
            session.commit()

        with Session(engine) as session:
            assert run_once(session, NOW) == 1

        with Session(engine) as session:  # a new session only sees committed work
            statuses = dict(session.execute(select(Booking.reference, Booking.status)).all())
            assert statuses == {expired: "expired", live: "held"}
    finally:
        engine.dispose()


def test_run_once_with_nothing_to_do_returns_zero(fresh_database_url: str) -> None:
    command.upgrade(alembic_config(fresh_database_url), "head")
    engine = make_engine(fresh_database_url)
    try:
        with Session(engine) as session:
            seed(session)
            session.commit()
        with Session(engine) as session:
            assert run_once(session, NOW) == 0
    finally:
        engine.dispose()
