"""Booking writes that don't go through free times still take turns with settings changes:
a payment arriving, and undoing a no-show. Each takes the shared lock before any row lock,
so the lock order is the same everywhere and they can't deadlock with a move."""

import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from alembic import command
from conftest import alembic_config
from factories import make_deposit, make_hold, make_staff
from fakes import FakeProvider
from sqlalchemy import Engine, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.db import make_engine
from app.models import Booking, StaffUser
from app.payments.service import complete_deposit
from app.schedule.changes import change_status
from app.seed import seed
from app.settings.lock import lock_exclusive

NOW = datetime(2026, 11, 9, 9, tzinfo=UTC)
START = datetime(2026, 11, 10, 8, tzinfo=UTC)
REF = "cs_lock_paths"
HOLD_FOR = 1.0  # seconds the admin's transaction keeps the exclusive lock


@pytest.fixture
def engine(fresh_database_url: str) -> Iterator[Engine]:
    command.upgrade(alembic_config(fresh_database_url), "head")
    made = make_engine(fresh_database_url)
    with Session(made) as session:
        seed(session)
        make_staff(session, role="admin", email="alex.admin@example.com")
        session.commit()
    yield made
    made.dispose()


def hold_exclusive(engine: Engine, locked: threading.Event, log: list[str]) -> None:
    """An admin's settings change: the exclusive lock, held for a while."""
    with Session(engine) as session:
        lock_exclusive(session)
        locked.set()
        time.sleep(HOLD_FOR)
        log.append("settings done")
        session.commit()


def row_is_locked(engine: Engine, booking_id: int) -> bool:
    with Session(engine) as session:
        try:
            session.execute(
                text("SELECT id FROM bookings WHERE id = :id FOR UPDATE NOWAIT"), {"id": booking_id}
            )
        except OperationalError:
            return True
        finally:
            session.rollback()
    return False


def test_payment_waits_for_the_lock_before_locking_the_booking(engine: Engine) -> None:
    with Session(engine) as session:
        booking = make_hold(session, START, NOW + timedelta(minutes=10), details=True)
        make_deposit(session, booking, ref=REF)
        session.commit()
        booking_id = booking.id
    provider = FakeProvider()
    provider.mark_paid(REF)

    locked, log = threading.Event(), list[str]()
    admin = threading.Thread(target=hold_exclusive, args=(engine, locked, log))
    admin.start()
    assert locked.wait(timeout=10)

    def pay() -> None:
        with Session(engine) as session:
            complete_deposit(session, provider, REF, NOW)
            log.append("paid")
            session.commit()

    payer = threading.Thread(target=pay)
    payer.start()
    time.sleep(HOLD_FOR / 3)  # long enough for the payment to reach the lock
    # Waiting for the shared lock, it holds no row lock a move could be waiting on.
    assert not row_is_locked(engine, booking_id)
    payer.join(timeout=10)
    admin.join(timeout=10)
    assert log == ["settings done", "paid"]


def test_undo_no_show_waits_for_a_settings_change(engine: Engine) -> None:
    with Session(engine) as session:
        booking = make_hold(session, START, NOW, status="confirmed")
        booking.status = "no_show"
        booking.status_changed_at = NOW  # undo is allowed for a while after
        session.commit()
        reference = booking.reference

    locked, log = threading.Event(), list[str]()
    admin = threading.Thread(target=hold_exclusive, args=(engine, locked, log))
    admin.start()
    assert locked.wait(timeout=10)
    with Session(engine) as session:
        staff = session.scalars(select(StaffUser)).one()
        change_status(session, staff, reference, "undo_no_show", NOW)
        log.append("undone")
        session.commit()
        status = session.scalars(select(Booking.status).where(Booking.reference == reference)).one()
    admin.join(timeout=10)
    assert log == ["settings done", "undone"]
    assert status == "confirmed"
