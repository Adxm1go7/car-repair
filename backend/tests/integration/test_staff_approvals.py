"""Staff answer a request: approve it, propose another time, or decline it."""

import threading
from datetime import UTC, datetime, timedelta

import pytest
from alembic import command
from conftest import alembic_config
from factories import make_deposit, make_hold, make_staff
from fakes import FakeProvider
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.db import make_engine
from app.models import AuditEntry, Bay, Booking, BookingItem, EmailLog, Payment, Service, StaffUser
from app.repositories.reservations import SlotUnavailable
from app.schedule.approvals import approve_booking, decline_booking, propose_booking
from app.schedule.changes import NotAllowed, garage_cancel
from app.seed import seed

NOW = datetime(2026, 11, 9, 9, tzinfo=UTC)  # Monday 09:00 in London (GMT)
START = datetime(2026, 11, 16, 9, tzinfo=UTC)  # a week ahead
LATER = datetime(2026, 11, 17, 10, tzinfo=UTC)


@pytest.fixture
def seeded(db_session: Session) -> Session:
    seed(db_session)
    return db_session


@pytest.fixture
def staff(seeded: Session) -> StaffUser:
    return make_staff(seeded)


def bay(session: Session, slug: str) -> int:
    return session.scalars(select(Bay.id).where(Bay.slug == slug)).one()


def request(
    session: Session,
    start: datetime = START,
    deadline: datetime = NOW + timedelta(hours=48),
    status: str = "pending_approval",
) -> Booking:
    """A one-hour diagnostic check in Bay 1, waiting for staff (or for its deposit)."""
    booking = make_hold(session, start, deadline, bay_slug="bay-1", status=status)
    check = session.scalars(select(Service).where(Service.slug == "diagnostic-check")).one()
    booking.items = [
        BookingItem(
            service_id=check.id,
            service_name=check.name,
            price_from_pence=check.price_from_pence,
            price_to_pence=check.price_to_pence,
            duration_minutes=60,
            position=0,
        )
    ]
    session.flush()
    return booking


def reload(session: Session, booking: Booking) -> Booking:
    session.expire_all()
    fresh = session.get(Booking, booking.id)
    assert fresh is not None
    return fresh


def emails(session: Session) -> list[EmailLog]:
    return list(session.scalars(select(EmailLog).order_by(EmailLog.id)))


def audit_actions(session: Session) -> list[str]:
    return list(session.scalars(select(AuditEntry.action).order_by(AuditEntry.id)))


# --- approve ---------------------------------------------------------------------


def test_approve_asks_for_the_deposit(seeded: Session, staff: StaffUser) -> None:
    booking = request(seeded)
    approve_booking(seeded, staff, booking.reference, NOW)
    booking = reload(seeded, booking)
    assert booking.status == "awaiting_deposit"
    assert booking.hold_expires_at == NOW + timedelta(hours=24)
    assert booking.reservation.active
    assert [e.template for e in emails(seeded)] == ["approved"]
    assert audit_actions(seeded) == ["booking.approve"]


def test_approve_overdue_request_refused(seeded: Session, staff: StaffUser) -> None:
    booking = request(seeded, deadline=NOW - timedelta(minutes=1))
    with pytest.raises(NotAllowed) as refused:
        approve_booking(seeded, staff, booking.reference, NOW)
    assert refused.value.detail == "expired"


def test_approve_a_confirmed_booking_refused(seeded: Session, staff: StaffUser) -> None:
    booking = make_hold(seeded, START, NOW, status="confirmed")
    with pytest.raises(NotAllowed) as refused:
        approve_booking(seeded, staff, booking.reference, NOW)
    assert refused.value.detail == "not_allowed"


def test_approve_too_close_to_pay_refused(seeded: Session, staff: StaffUser) -> None:
    soon = NOW + timedelta(hours=3)
    booking = request(seeded, start=soon, deadline=NOW + timedelta(minutes=30))
    with pytest.raises(NotAllowed) as refused:
        approve_booking(seeded, staff, booking.reference, NOW)
    assert refused.value.detail == "too_soon"
    assert reload(seeded, booking).status == "pending_approval"


def test_unknown_booking_is_a_lookup_error(seeded: Session, staff: StaffUser) -> None:
    with pytest.raises(LookupError):
        approve_booking(seeded, staff, "NONE-0000", NOW)


# --- propose ---------------------------------------------------------------------


def test_propose_moves_and_approves(seeded: Session, staff: StaffUser) -> None:
    booking = request(seeded)
    provider = FakeProvider()
    propose_booking(
        seeded, provider, staff, booking.reference, LATER, bay(seeded, "bay-2"), "Parts", NOW
    )
    booking = reload(seeded, booking)
    assert (booking.status, booking.start_at) == ("awaiting_deposit", LATER)
    assert booking.reservation.bay_id == bay(seeded, "bay-2")
    assert booking.hold_expires_at == NOW + timedelta(hours=24)
    [email] = emails(seeded)
    assert email.template == "proposed"
    assert email.context is not None
    assert email.context["previous_start"] == START.isoformat()
    assert email.context["reason"] == "Parts"
    assert audit_actions(seeded) == ["booking.propose"]


def test_propose_too_soon_refused(seeded: Session, staff: StaffUser) -> None:
    booking = request(seeded)
    soon = NOW + timedelta(hours=3)
    with pytest.raises(NotAllowed) as refused:
        propose_booking(
            seeded, FakeProvider(), staff, booking.reference, soon, bay(seeded, "bay-2"), None, NOW
        )
    assert refused.value.detail == "too_soon"
    booking = reload(seeded, booking)
    assert (booking.status, booking.start_at) == ("pending_approval", START)
    assert emails(seeded) == []


def test_propose_into_a_taken_time_refused(seeded: Session, staff: StaffUser) -> None:
    booking = request(seeded)
    make_hold(seeded, LATER, NOW + timedelta(minutes=5), bay_slug="bay-2")
    with pytest.raises(SlotUnavailable):
        propose_booking(
            seeded, FakeProvider(), staff, booking.reference, LATER, bay(seeded, "bay-2"), None, NOW
        )


def test_propose_again_closes_the_open_form(seeded: Session, staff: StaffUser) -> None:
    booking = request(seeded, deadline=NOW + timedelta(hours=2), status="awaiting_deposit")
    deposit = make_deposit(seeded, booking, ref="cs_fake_1")
    provider = FakeProvider()
    propose_booking(
        seeded, provider, staff, booking.reference, LATER, bay(seeded, "bay-2"), None, NOW
    )
    assert provider.called("close_checkout") == [{"session_ref": "cs_fake_1"}]
    seeded.expire_all()
    assert seeded.get(Payment, deposit.id).status == "expired"  # type: ignore[union-attr]
    assert reload(seeded, booking).hold_expires_at == NOW + timedelta(hours=24)


# --- decline and cancel ----------------------------------------------------------


def test_decline_frees_the_time(seeded: Session, staff: StaffUser) -> None:
    booking = request(seeded)
    decline_booking(seeded, staff, booking.reference, "We don't do that model", NOW)
    booking = reload(seeded, booking)
    assert booking.status == "cancelled"
    assert not booking.reservation.active
    [email] = emails(seeded)
    assert email.template == "declined"
    assert email.context == {"reason": "We don't do that model"}
    assert audit_actions(seeded) == ["booking.decline"]


def test_decline_an_approval_refused(seeded: Session, staff: StaffUser) -> None:
    booking = request(seeded, status="awaiting_deposit")
    with pytest.raises(NotAllowed):
        decline_booking(seeded, staff, booking.reference, None, NOW)


def test_garage_cancel_of_an_approval_closes_its_form(seeded: Session, staff: StaffUser) -> None:
    booking = request(seeded, status="awaiting_deposit")
    make_deposit(seeded, booking, ref="cs_fake_1")
    provider = FakeProvider()
    garage_cancel(seeded, provider, staff, booking.reference, None, NOW, 24)
    assert provider.called("close_checkout") == [{"session_ref": "cs_fake_1"}]
    assert reload(seeded, booking).status == "cancelled"


# --- two staff at once -----------------------------------------------------------


def race(engine: Engine, reference: str, staff_id: int, actions: list[str]) -> list[str]:
    barrier = threading.Barrier(len(actions))
    outcomes: list[str] = []

    def press(action: str) -> None:
        with Session(engine) as session:
            staff = session.get(StaffUser, staff_id)
            assert staff is not None
            barrier.wait()
            try:
                if action == "approve":
                    approve_booking(session, staff, reference, NOW)
                else:
                    decline_booking(session, staff, reference, None, NOW)
                session.commit()
                outcomes.append(action)
            except NotAllowed:
                session.rollback()
                outcomes.append("refused")

    threads = [threading.Thread(target=press, args=(a,)) for a in actions]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return outcomes


def test_approve_and_decline_at_once_one_wins(fresh_database_url: str) -> None:
    command.upgrade(alembic_config(fresh_database_url), "head")
    engine = make_engine(fresh_database_url)
    try:
        with Session(engine) as session:
            seed(session)
            staff_id = make_staff(session).id
            reference = request(session).reference
            session.commit()
        outcomes = race(engine, reference, staff_id, ["approve", "decline"])
        assert "refused" in outcomes
        assert len(outcomes) == 2
        with Session(engine) as session:
            assert session.scalar(select(func.count()).select_from(AuditEntry)) == 1
            assert session.scalar(select(func.count()).select_from(EmailLog)) == 1
    finally:
        engine.dispose()
