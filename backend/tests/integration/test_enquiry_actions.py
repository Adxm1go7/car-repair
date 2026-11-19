"""Staff book an enquiry in (through the phone-booking code) or decline it. Once handled, it
can't be handled again, even by two staff at the same moment."""

import threading
from datetime import UTC, datetime, timedelta

import pytest
from alembic import command
from conftest import alembic_config
from factories import make_enquiry, make_hold, make_staff
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.db import make_engine
from app.enquiries.actions import EnquiryNotNew, approve_enquiry, decline_enquiry
from app.models import AuditEntry, Bay, Booking, EmailLog, Enquiry, Service, StaffUser
from app.repositories.reservations import SlotUnavailable
from app.schedule.phone import PhoneDetails
from app.seed import seed

NOW = datetime(2026, 11, 9, 9, tzinfo=UTC)  # Monday 09:00 in London (GMT)
START = datetime(2026, 11, 10, 9, tzinfo=UTC)  # Tuesday 09:00
DETAILS = PhoneDetails(
    name="Sam Driver",
    phone="07700 900123",
    email="sam@example.com",
    registration="AB12CDE",
    make="Ford",
    model="Focus",
    notes="Rattle from the front left when braking",
)


@pytest.fixture
def seeded(db_session: Session) -> Session:
    seed(db_session)
    return db_session


@pytest.fixture
def staff(seeded: Session) -> StaffUser:
    return make_staff(seeded)


def mot(session: Session) -> list[Service]:
    return [session.scalars(select(Service).where(Service.slug == "mot-test")).one()]


def mot_bay(session: Session) -> int:
    return session.scalars(select(Bay.id).where(Bay.slug == "mot-bay")).one()


def approve(
    session: Session, staff: StaffUser, enquiry: Enquiry, start: datetime = START
) -> Enquiry:
    return approve_enquiry(
        session, staff, enquiry.id, mot(session), start, mot_bay(session), DETAILS, NOW
    )


def templates(session: Session) -> list[str]:
    return list(session.scalars(select(EmailLog.template).order_by(EmailLog.id)))


def actions(session: Session) -> list[str]:
    return list(session.scalars(select(AuditEntry.action).order_by(AuditEntry.id)))


def test_approve_makes_confirmed_no_deposit_booking(seeded: Session, staff: StaffUser) -> None:
    enquiry = make_enquiry(seeded)
    approve(seeded, staff, enquiry)
    booking = enquiry.booking
    assert booking is not None
    assert (booking.status, booking.source, booking.deposit_status) == (
        "confirmed",
        "enquiry",
        "not_required",
    )
    assert (booking.start_at, booking.reservation.bay_id) == (START, mot_bay(seeded))
    assert booking.customer_email == "sam@example.com"
    assert booking.notes == "Rattle from the front left when braking"
    assert (enquiry.status, enquiry.handled_by, enquiry.handled_at) == ("converted", staff.id, NOW)
    assert templates(seeded) == ["confirmation"]
    assert actions(seeded) == ["booking.create", "enquiry.approve"]
    entry = seeded.scalars(select(AuditEntry).where(AuditEntry.action == "enquiry.approve")).one()
    assert (entry.entity_type, entry.entity_id) == ("enquiry", enquiry.id)
    assert entry.booking_reference == booking.reference
    create = seeded.scalars(select(AuditEntry).where(AuditEntry.action == "booking.create")).one()
    assert create.after is not None
    assert create.after["source"] == "enquiry"


def test_approve_taken_slot_leaves_enquiry_new(seeded: Session, staff: StaffUser) -> None:
    make_hold(seeded, START, START, status="confirmed")
    enquiry = make_enquiry(seeded)
    seeded.commit()
    with pytest.raises(SlotUnavailable):
        approve(seeded, staff, enquiry)
    seeded.rollback()
    seeded.refresh(enquiry)
    assert (enquiry.status, enquiry.booking_id, enquiry.handled_at) == ("new", None, None)
    assert templates(seeded) == []
    assert "enquiry.approve" not in actions(seeded)


def test_decline_with_reason(seeded: Session, staff: StaffUser) -> None:
    enquiry = make_enquiry(seeded)
    decline_enquiry(seeded, staff, enquiry.id, "Too busy this month", NOW)
    assert (enquiry.status, enquiry.decline_reason) == ("declined", "Too busy this month")
    assert (enquiry.handled_by, enquiry.handled_at) == (staff.id, NOW)
    (email,) = seeded.scalars(select(EmailLog))
    assert (email.template, email.enquiry_id) == ("enquiry_declined", enquiry.id)
    assert email.context == {"reason": "Too busy this month"}
    entry = seeded.scalars(select(AuditEntry)).one()
    assert (entry.action, entry.entity_type, entry.entity_id) == (
        "enquiry.decline",
        "enquiry",
        enquiry.id,
    )
    assert entry.reason == "Too busy this month"


def test_decline_without_reason(seeded: Session, staff: StaffUser) -> None:
    enquiry = make_enquiry(seeded)
    decline_enquiry(seeded, staff, enquiry.id, None, NOW)
    assert (enquiry.status, enquiry.decline_reason) == ("declined", None)
    (email,) = seeded.scalars(select(EmailLog))
    assert email.context == {"reason": None}


@pytest.mark.parametrize("status", ["converted", "declined"])
@pytest.mark.parametrize("action", ["approve", "decline"])
def test_not_new_refused(seeded: Session, staff: StaffUser, status: str, action: str) -> None:
    enquiry = make_enquiry(seeded, status=status, created_at=NOW - timedelta(days=1))
    with pytest.raises(EnquiryNotNew):
        if action == "approve":
            approve(seeded, staff, enquiry, START + timedelta(days=1))
        else:
            decline_enquiry(seeded, staff, enquiry.id, None, NOW)


def test_unknown_enquiry(seeded: Session, staff: StaffUser) -> None:
    with pytest.raises(LookupError):
        decline_enquiry(seeded, staff, 999_999, None, NOW)


# --- two staff at once --------------------------------------------------------------


def race(
    engine: Engine,
    enquiry_id: int,
    start: datetime,
    barrier: threading.Barrier,
    outcomes: list[str],
) -> None:
    with Session(engine) as session:
        try:
            staff = session.scalars(select(StaffUser)).first()
            assert staff is not None
            services, bay = mot(session), mot_bay(session)
            barrier.wait(timeout=10)
            approve_enquiry(session, staff, enquiry_id, services, start, bay, DETAILS, NOW)
            session.commit()
            outcomes.append("won")
        except EnquiryNotNew:
            session.rollback()
            outcomes.append("not_new")
        except Exception as error:  # surfaced by the assertion in the test
            outcomes.append(f"error: {error!r}")


def test_two_approvals_make_one_booking(fresh_database_url: str) -> None:
    command.upgrade(alembic_config(fresh_database_url), "head")
    engine = make_engine(fresh_database_url)
    try:
        with Session(engine) as session:
            seed(session)
            make_staff(session)
            enquiry_id = make_enquiry(session).id
            session.commit()
        barrier = threading.Barrier(2)
        outcomes: list[str] = []
        starts = [START, START + timedelta(hours=3)]  # different free times: no slot clash
        threads = [
            threading.Thread(target=race, args=(engine, enquiry_id, start, barrier, outcomes))
            for start in starts
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        assert sorted(outcomes) == ["not_new", "won"], outcomes
        with Session(engine) as session:
            booked = session.scalar(
                select(func.count()).select_from(Booking).where(Booking.source == "enquiry")
            )
            assert booked == 1
    finally:
        engine.dispose()
