"""The database refuses enquiries, enquiry bookings and enquiry emails that break the rules."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from factories import make_hold, make_staff
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Booking, EmailLog, Enquiry
from app.seed import seed

NOW = datetime(2026, 11, 19, 9, tzinfo=UTC)
START = datetime(2026, 11, 25, 9, tzinfo=UTC)


@pytest.fixture(autouse=True)
def seeded(db_session: Session) -> None:
    seed(db_session)


def enquiry(**changes: Any) -> Enquiry:
    values: dict[str, Any] = {
        "customer_name": "Sam Driver",
        "customer_phone": "07700 900123",
        "customer_email": "sam@example.com",
        "car_registration": "AB12CDE",
        "car_make": "Ford",
        "car_model": "Focus",
        "description": "Rattle from the front left when braking",
        **changes,
    }
    return Enquiry(**values)


def refused(session: Session, row: object, constraint: str) -> None:
    with pytest.raises(IntegrityError, match=constraint), session.begin_nested():
        session.add(row)
        session.flush()


def confirmed_booking(session: Session) -> Booking:
    return make_hold(session, START, START - timedelta(days=5), status="confirmed")


def test_new_enquiry_flushes(db_session: Session) -> None:
    row = enquiry()
    db_session.add(row)
    db_session.flush()
    db_session.refresh(row)
    assert row.status == "new"
    assert row.created_at is not None


def test_converted_needs_booking(db_session: Session) -> None:
    staff = make_staff(db_session)
    refused(
        db_session,
        enquiry(status="converted", handled_at=NOW, handled_by=staff.id),
        "ck_enquiries_booking_only_when_converted",
    )
    booking = confirmed_booking(db_session)
    refused(db_session, enquiry(booking_id=booking.id), "ck_enquiries_booking_only_when_converted")


def test_handled_needs_who_and_when(db_session: Session) -> None:
    staff = make_staff(db_session)
    refused(db_session, enquiry(status="declined", handled_by=staff.id), "handled_unless_new")
    refused(db_session, enquiry(handled_at=NOW), "handled_unless_new")


def test_status_must_be_known(db_session: Session) -> None:
    staff = make_staff(db_session)
    refused(
        db_session,
        enquiry(status="open", handled_at=NOW, handled_by=staff.id),
        "ck_enquiries_status_valid",
    )


def test_enquiry_booking_needs_no_deposit_and_may_be_confirmed(db_session: Session) -> None:
    booking = confirmed_booking(db_session)
    booking.source = "enquiry"
    booking.deposit_status = "not_required"
    db_session.flush()
    online = make_hold(db_session, START + timedelta(hours=3), START, status="confirmed")
    online.deposit_status = "not_required"
    with pytest.raises(IntegrityError, match="not_required_only_by_phone"):
        db_session.flush()


def enquiry_email(row: Enquiry, **changes: Any) -> EmailLog:
    values: dict[str, Any] = {
        "template": "enquiry_received",
        "enquiry_id": row.id,
        "recipient": "sam@example.com",
        **changes,
    }
    return EmailLog(**values)


def test_enquiry_email_has_one_subject(db_session: Session) -> None:
    row = enquiry()
    db_session.add(row)
    db_session.flush()
    db_session.add(enquiry_email(row))
    db_session.flush()
    booking = confirmed_booking(db_session)
    refused(
        db_session,
        enquiry_email(row, booking_id=booking.id),
        "ck_email_log_has_one_subject",
    )
    refused(
        db_session,
        EmailLog(template="enquiry_received", recipient="sam@example.com"),
        "ck_email_log_has_one_subject",
    )


@pytest.mark.parametrize("template", ["enquiry_received", "enquiry_declined"])
def test_enquiry_templates_allowed(db_session: Session, template: str) -> None:
    row = enquiry()
    db_session.add(row)
    db_session.flush()
    db_session.add(enquiry_email(row, template=template))
    db_session.flush()
