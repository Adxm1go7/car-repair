"""The worker releases expired holds and closes their payment forms, committing as it goes."""

from datetime import UTC, datetime, timedelta

from alembic import command
from conftest import alembic_config
from factories import make_deposit, make_hold
from fakes import FakeProvider
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.db import make_engine
from app.models import Booking, Payment
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
            assert run_once(session, NOW, FakeProvider()) == 1

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
            assert run_once(session, NOW, FakeProvider()) == 0
    finally:
        engine.dispose()


START = datetime(2026, 11, 10, 8, tzinfo=UTC)


def worker_database(url: str) -> Engine:
    command.upgrade(alembic_config(url), "head")
    engine = make_engine(url)
    with Session(engine) as session:
        seed(session)
        session.commit()
    return engine


def paying_hold(engine: Engine, expires_at: datetime) -> str:
    """A hold whose payment form cs_fake_1 is open. Returns its reference."""
    with Session(engine) as session:
        booking = make_hold(session, START, expires_at, details=True)
        make_deposit(session, booking, ref="cs_fake_1")
        session.commit()
        return booking.reference


def state(engine: Engine, reference: str) -> tuple[str, str, str]:
    with Session(engine) as session:
        booking = session.scalars(select(Booking).where(Booking.reference == reference)).one()
        deposit = session.scalars(select(Payment).where(Payment.booking_id == booking.id)).one()
        return booking.status, booking.deposit_status, deposit.status


def test_worker_closes_checkout_of_a_released_hold(fresh_database_url: str) -> None:
    engine = worker_database(fresh_database_url)
    try:
        reference = paying_hold(engine, NOW - timedelta(minutes=1))
        provider = FakeProvider()
        with Session(engine) as session:
            assert run_once(session, NOW, provider) == 1
        assert provider.called("close_checkout") == [{"session_ref": "cs_fake_1"}]
        assert state(engine, reference) == ("expired", "unpaid", "expired")
    finally:
        engine.dispose()


def test_worker_leaves_a_live_payment_form_open(fresh_database_url: str) -> None:
    engine = worker_database(fresh_database_url)
    try:
        reference = paying_hold(engine, NOW + timedelta(minutes=5))
        provider = FakeProvider()
        with Session(engine) as session:
            run_once(session, NOW, provider)
        assert provider.calls == []
        assert state(engine, reference) == ("held", "unpaid", "open")
    finally:
        engine.dispose()


def test_worker_retries_a_failed_close_next_cycle(fresh_database_url: str) -> None:
    engine = worker_database(fresh_database_url)
    try:
        reference = paying_hold(engine, NOW - timedelta(minutes=1))
        provider = FakeProvider(fail=True)
        with Session(engine) as session:
            assert run_once(session, NOW, provider) == 1  # the release still happens
        assert state(engine, reference) == ("expired", "unpaid", "open")

        provider.fail = False
        with Session(engine) as session:
            assert run_once(session, NOW + timedelta(minutes=1), provider) == 0
        assert state(engine, reference) == ("expired", "unpaid", "expired")
    finally:
        engine.dispose()


def test_worker_completes_a_deposit_that_got_in(fresh_database_url: str) -> None:
    engine = worker_database(fresh_database_url)
    try:
        reference = paying_hold(engine, NOW - timedelta(minutes=1))
        provider = FakeProvider()
        provider.mark_paid("cs_fake_1")  # paid just before the hold ran out
        with Session(engine) as session:
            run_once(session, NOW, provider)
        # Released, then the close found the payment: the time was still free, so it's booked.
        assert state(engine, reference) == ("confirmed", "paid", "paid")
    finally:
        engine.dispose()
