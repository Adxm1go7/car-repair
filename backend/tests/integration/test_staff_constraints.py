"""The database refuses staff, block, audit and booking rows that break the rules."""

from datetime import UTC, datetime, timedelta

import pytest
from factories import BUFFER, CUSTOMER
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.bookings.rules import new_reference
from app.models import Bay, Block, Booking, EmailLog, Reservation, StaffUser
from app.seed import seed

START = datetime(2026, 11, 20, 9, tzinfo=UTC)


@pytest.fixture
def seeded(db_session: Session) -> Session:
    seed(db_session)
    return db_session


def staff(email: str = "sam.staff@example.com", role: str = "staff") -> StaffUser:
    return StaffUser(name="Sam Staff", email=email, role=role)


def reservation(session: Session, start: datetime = START) -> Reservation:
    bay = session.scalars(select(Bay.id).where(Bay.slug == "mot-bay")).one()
    row = Reservation(
        bay_id=bay, kind="booking", during=Range(start, start + timedelta(hours=1) + BUFFER)
    )
    session.add(row)
    session.flush()
    return row


def confirmed_booking(session: Session, **changes: object) -> Booking:
    """A confirmed booking with every detail, changed by `changes`."""
    values: dict[str, object] = {
        "reference": new_reference(),
        "reservation_id": reservation(session).id,
        "status": "confirmed",
        "start_at": START,
        "end_at": START + timedelta(hours=1),
        "deposit_status": "paid",
        **CUSTOMER,
        **changes,
    }
    return Booking(**values)


def refused(session: Session, row: object) -> None:
    with pytest.raises(IntegrityError), session.begin_nested():
        session.add(row)
        session.flush()


def test_staff_email_is_unique(seeded: Session) -> None:
    seeded.add(staff())
    seeded.flush()
    refused(seeded, staff())


def test_unknown_role_is_rejected(seeded: Session) -> None:
    refused(seeded, staff(role="owner"))


def test_not_required_deposit_needs_phone_source(seeded: Session) -> None:
    refused(seeded, confirmed_booking(seeded, deposit_status="not_required"))


def test_phone_booking_may_have_no_email(seeded: Session) -> None:
    seeded.add(
        confirmed_booking(
            seeded, source="phone", customer_email=None, deposit_status="not_required"
        )
    )
    seeded.flush()


def test_online_confirmed_booking_still_needs_email(seeded: Session) -> None:
    refused(seeded, confirmed_booking(seeded, customer_email=None))


def test_new_bookings_are_online_by_default(seeded: Session) -> None:
    booking = confirmed_booking(seeded)
    seeded.add(booking)
    seeded.flush()
    seeded.refresh(booking)
    assert booking.source == "online"


def test_block_reservation_needs_a_block(seeded: Session) -> None:
    bay = seeded.scalars(select(Bay.id).where(Bay.slug == "bay-1")).one()
    refused(
        seeded,
        Reservation(bay_id=bay, kind="block", during=Range(START, START + timedelta(hours=1))),
    )


def test_block_reservation_with_its_block_is_fine(seeded: Session) -> None:
    creator = staff()
    seeded.add(creator)
    seeded.flush()
    block = Block(
        start_at=START, end_at=START + timedelta(hours=1), note="Lift broken", created_by=creator.id
    )
    seeded.add(block)
    seeded.flush()
    bay = seeded.scalars(select(Bay.id).where(Bay.slug == "bay-1")).one()
    seeded.add(
        Reservation(
            bay_id=bay,
            kind="block",
            block_id=block.id,
            during=Range(START, START + timedelta(hours=1)),
        )
    )
    seeded.flush()


def test_email_log_needs_exactly_one_subject(seeded: Session) -> None:
    booking = confirmed_booking(seeded)
    user = staff()
    seeded.add_all([booking, user])
    seeded.flush()
    refused(seeded, EmailLog(template="staff_invite", recipient="x@example.com"))
    refused(
        seeded,
        EmailLog(
            template="staff_invite",
            recipient="x@example.com",
            booking_id=booking.id,
            staff_user_id=user.id,
        ),
    )
    seeded.add(EmailLog(template="staff_invite", recipient=user.email, staff_user_id=user.id))
    seeded.flush()
