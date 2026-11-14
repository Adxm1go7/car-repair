"""A customer moves to payment just as the sweep expires their hold. One must win cleanly."""

import threading
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from alembic import command
from conftest import alembic_config
from factories import TEST_TOKEN, make_hold
from fakes import FakeProvider
from sqlalchemy.orm import Session

from app.bookings.service import CustomerDetails, HoldExpired, start_checkout
from app.db import make_engine
from app.models import Booking
from app.repositories.bookings import release_expired_holds
from app.seed import seed

EXPIRES = datetime(2026, 11, 9, 9, 10, tzinfo=UTC)
DETAILS = CustomerDetails(
    name="Sam Driver",
    phone="07700 900123",
    email="sam@example.com",
    registration="AB12CDE",
    make="Ford",
    model="Focus",
    notes=None,
)
ROUNDS = 10
PAYMENT_HOLD = timedelta(minutes=10)


def test_checkout_and_sweep_never_mix(fresh_database_url: str) -> None:
    command.upgrade(alembic_config(fresh_database_url), "head")
    engine = make_engine(fresh_database_url)
    try:
        with Session(engine) as session:
            seed(session)
            # One hold per round, each on its own day so they never overlap.
            references = [
                make_hold(
                    session, datetime(2026, 11, 10, 10, tzinfo=UTC) + timedelta(days=n), EXPIRES
                ).reference
                for n in range(ROUNDS)
            ]
            session.commit()

        for reference in references:
            barrier = threading.Barrier(2)
            errors: list[str] = []

            def customer(
                reference: str = reference,
                barrier: threading.Barrier = barrier,
                errors: list[str] = errors,
            ) -> None:
                with Session(engine) as session:
                    try:
                        barrier.wait(timeout=10)
                        # One second before expiry by the customer's request clock.
                        start_checkout(
                            session,
                            FakeProvider(),
                            reference,
                            TEST_TOKEN,
                            DETAILS,
                            EXPIRES - timedelta(seconds=1),
                            payment_hold_minutes=10,
                            amount_pence=2000,
                            zone=ZoneInfo("Europe/London"),
                        )
                        session.commit()
                    except HoldExpired:
                        session.commit()
                    except Exception as error:
                        errors.append(repr(error))

            def sweep(barrier: threading.Barrier = barrier, errors: list[str] = errors) -> None:
                with Session(engine) as session:
                    try:
                        barrier.wait(timeout=10)
                        release_expired_holds(session, EXPIRES)
                        session.commit()
                    except Exception as error:
                        errors.append(repr(error))

            threads = [threading.Thread(target=customer), threading.Thread(target=sweep)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=30)
            assert errors == []

            with Session(engine) as session:
                booking = session.query(Booking).filter_by(reference=reference).one()
                moved_on = EXPIRES - timedelta(seconds=1) + PAYMENT_HOLD
                state = (booking.status, booking.reservation.active, booking.hold_expires_at)
                assert state in {("held", True, moved_on), ("expired", False, EXPIRES)}, state
    finally:
        engine.dispose()
