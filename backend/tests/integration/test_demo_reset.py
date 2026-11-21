"""The live demo's reset: every data table emptied, then the normal seed, in one go."""

import threading
from datetime import UTC, datetime, timedelta

import pytest
from factories import make_hold, make_staff
from sqlalchemy import func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.config import AppConfig
from app.db import make_engine
from app.demo.reset import reset_demo
from app.demo_data import DEMO_STAFF
from app.demo_reset import main as demo_reset_main
from app.models import Booking, DemoInboxEmail, Enquiry, Setting, StaffUser
from app.repositories.catalogue import get_setting
from app.seed import DEFAULT_SETTINGS, seed
from app.settings.lock import lock_shared

START = datetime(2026, 11, 20, 9, tzinfo=UTC)
NOW = datetime(2026, 11, 9, 9, tzinfo=UTC)


def count(session: Session, model: type) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


def visitor_activity(session: Session) -> Booking:
    """What a day of visitors leaves behind: a booking, an enquiry, an inbox email, an
    invited colleague and a changed garage name."""
    seed(session, sample_accounts=True)
    booking = make_hold(session, START, NOW + timedelta(minutes=10), status="confirmed")
    session.add(
        Enquiry(
            customer_name="Ann",
            customer_phone="07700 900123",
            customer_email="ann@example.com",
            car_registration="AB12 CDE",
            car_make="Ford",
            car_model="Fiesta",
            description="Squeaky brakes",
        )
    )
    session.add(
        DemoInboxEmail(template="confirmation", recipient="a@b.c", subject="s", text="t", html="h")
    )
    make_staff(session, email="nia@example.test", name="Nia New")
    contact = session.get(Setting, "garage_contact")
    assert contact is not None
    contact.value = {**DEFAULT_SETTINGS["garage_contact"], "name": "Defaced Motors"}
    session.commit()
    return booking


def test_reset_wipes_visitor_data_and_reseeds(db_session: Session) -> None:
    visitor_activity(db_session)

    reset_demo(db_session)
    db_session.commit()
    db_session.expire_all()

    assert count(db_session, Booking) == 0
    assert count(db_session, Enquiry) == 0
    assert count(db_session, DemoInboxEmail) == 0
    emails = set(db_session.scalars(select(StaffUser.email)))
    assert emails == {staff.email for staff in DEMO_STAFF}
    assert get_setting(db_session, "garage_contact") == DEFAULT_SETTINGS["garage_contact"]


def test_reset_keeps_ids_running(db_session: Session) -> None:
    before = visitor_activity(db_session).id

    reset_demo(db_session)
    db_session.commit()
    after = make_hold(db_session, START, NOW + timedelta(minutes=10))

    assert after.id > before


def test_reset_keeps_alembic_version(db_session: Session) -> None:
    reset_demo(db_session)
    db_session.commit()
    version = db_session.scalar(text("SELECT version_num FROM alembic_version"))
    assert version is not None


def test_reset_waits_for_bookings_in_progress(migrated_url: str) -> None:
    """A booking being made holds the shared lock; the reset needs it exclusive."""
    engine = make_engine(migrated_url)
    holding = threading.Event()
    release = threading.Event()

    def make_a_booking() -> None:
        with Session(engine) as booking_session:
            lock_shared(booking_session)
            holding.set()
            release.wait(10)
            booking_session.rollback()

    booker = threading.Thread(target=make_a_booking)
    booker.start()
    try:
        assert holding.wait(10)
        with Session(engine) as session:
            session.execute(text("SET lock_timeout = '1s'"))
            with pytest.raises(OperationalError, match="lock timeout"):
                reset_demo(session)
            session.rollback()
    finally:
        release.set()
        booker.join()
        engine.dispose()


def test_demo_reset_command_refuses_when_off(
    migrated_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert demo_reset_main(AppConfig(database_url=migrated_url)) == 1
    assert "DEMO_SITE is off: refusing to reset" in capsys.readouterr().err
