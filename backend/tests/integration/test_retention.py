"""The 12-month rule: old bookings and enquiries keep their rows but lose the customer's
details, along with the copies in the audit log and the email log."""

from datetime import UTC, datetime, timedelta
from typing import Any

from factories import make_enquiry, make_hold, make_staff
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import AuditEntry, Booking, EmailLog
from app.privacy.retention import remove_old_details
from app.seed import seed
from app.staff.audit import record_audit

NOW = datetime(2027, 12, 1, 9, tzinfo=UTC)
OLD = NOW - timedelta(days=400)  # about 13 months ago
RECENT = NOW - timedelta(days=335)  # about 11 months ago


def old_booking(session: Session, start: datetime = OLD, status: str = "completed") -> Booking:
    booking = make_hold(session, start, start, status=status, details=True)
    booking.notes = "Please call Sam on his mobile"
    if status == "completed":
        booking.deposit_status = "paid"
    session.flush()
    return booking


def audit_for(session: Session, booking: Booking) -> AuditEntry:
    return record_audit(
        session,
        make_staff(session, email="alex.admin@example.com", name="Alex Admin"),
        "booking.create",
        "booking",
        booking.id,
        after={
            "services": ["MOT"],
            "name": "Sam Driver",
            "phone": "07700 900123",
            "email": "sam@example.com",
            "registration": "AB12CDE",
            "notes": "Please call Sam",
            "make": "Ford",
        },
        reason="Sam rang to book",
        booking_reference=booking.reference,
        now=OLD,
    )


def email_for(session: Session, status: str = "sent", **subject: Any) -> EmailLog:
    email = EmailLog(
        template="confirmation",
        recipient="sam@example.com",
        context={"name": "Sam Driver"},
        status=status,
        last_error="550 sam@example.com refused" if status == "failed" else None,
        **subject,
    )
    session.add(email)
    session.flush()
    return email


def test_old_booking_is_blanked(db_session: Session) -> None:
    seed(db_session)
    booking = old_booking(db_session)

    assert remove_old_details(db_session, NOW) == 1

    db_session.refresh(booking)
    assert booking.customer_name == "removed"
    assert booking.customer_phone == "removed"
    assert booking.customer_email == "removed"
    assert booking.car_registration == "REMOVED"
    assert booking.notes is None
    assert (booking.car_make, booking.car_model) == ("Ford", "Focus")
    assert booking.details_removed_at == NOW


def test_audit_and_email_rows_are_blanked(db_session: Session) -> None:
    seed(db_session)
    booking = old_booking(db_session)
    entry = audit_for(db_session, booking)
    sent = email_for(db_session, booking_id=booking.id)
    failed = email_for(db_session, status="failed", booking_id=booking.id)

    remove_old_details(db_session, NOW)

    db_session.refresh(entry)
    assert entry.after is not None
    for key in ("name", "phone", "email", "registration", "notes"):
        assert entry.after[key] == "removed"
    assert entry.after["services"] == ["MOT"]
    assert entry.after["make"] == "Ford"
    assert entry.reason == "removed"
    for email in (sent, failed):
        db_session.refresh(email)
        assert email.recipient == "removed"
        assert email.context is None
        assert email.last_error is None


def test_queued_email_is_skipped(db_session: Session) -> None:
    seed(db_session)
    booking = old_booking(db_session)
    queued = email_for(db_session, status="queued", booking_id=booking.id)

    remove_old_details(db_session, NOW)

    db_session.refresh(queued)
    assert queued.recipient == "sam@example.com"
    assert queued.context == {"name": "Sam Driver"}


def test_old_unhandled_and_declined_enquiries_are_blanked(db_session: Session) -> None:
    seed(db_session)
    new = make_enquiry(db_session, created_at=OLD)
    declined = make_enquiry(
        db_session, status="declined", created_at=OLD, reason="Sam's car is too old"
    )
    entry = record_audit(
        db_session,
        make_staff(db_session, email="alex.admin@example.com", name="Alex Admin"),
        "enquiry.decline",
        "enquiry",
        declined.id,
        after={"status": "declined"},
        reason="Sam's car is too old",
        now=OLD,
    )
    email = email_for(db_session, enquiry_id=declined.id)

    assert remove_old_details(db_session, NOW) == 2

    for enquiry in (new, declined):
        db_session.refresh(enquiry)
        assert enquiry.customer_name == "removed"
        assert enquiry.customer_phone == "removed"
        assert enquiry.customer_email == "removed"
        assert enquiry.car_registration == "REMOVED"
        assert enquiry.description == "removed"
        assert enquiry.details_removed_at == NOW
    assert declined.decline_reason == "removed"
    assert new.decline_reason is None
    db_session.refresh(entry)
    assert entry.reason == "removed"
    assert entry.after == {"status": "declined"}
    db_session.refresh(email)
    assert email.recipient == "removed"


def test_converted_enquiry_follows_its_booking(db_session: Session) -> None:
    seed(db_session)
    # Created 13 months ago; make_enquiry books it in 3 days later, so that booking is old too.
    old = make_enquiry(db_session, status="converted", created_at=OLD)
    # Created 13 months ago but booked in for 11 months ago: the booking isn't old yet.
    later = make_enquiry(db_session, status="converted", created_at=OLD + timedelta(hours=2))
    assert later.booking is not None
    later.booking.start_at = RECENT
    later.booking.end_at = RECENT + timedelta(hours=1)
    db_session.flush()

    assert remove_old_details(db_session, NOW) == 2  # the old one and its booking

    db_session.refresh(old)
    db_session.refresh(later)
    assert old.customer_name == "removed"
    assert old.booking is not None and old.booking.customer_name == "removed"
    assert later.customer_name == "Sam Driver"
    assert later.booking.customer_name == "Sam Driver"
    assert later.details_removed_at is None


def test_recent_and_waiting_are_untouched(db_session: Session) -> None:
    seed(db_session)
    recent = old_booking(db_session, start=RECENT)
    waiting = old_booking(db_session, start=OLD, status="pending_approval")
    held = old_booking(db_session, start=OLD + timedelta(hours=2), status="held")
    enquiry = make_enquiry(db_session, created_at=RECENT)

    assert remove_old_details(db_session, NOW) == 0

    for row in (recent, waiting, held, enquiry):
        db_session.refresh(row)
        assert row.customer_name == "Sam Driver"
        assert row.details_removed_at is None


def test_null_fields_stay_null(db_session: Session) -> None:
    seed(db_session)
    abandoned = make_hold(db_session, OLD, OLD, status="expired")
    for field in ("customer_name", "customer_phone", "customer_email", "car_registration"):
        setattr(abandoned, field, None)  # it never got details
    phone = old_booking(db_session, start=OLD + timedelta(hours=2))
    phone.source = "phone"
    phone.customer_email = None
    phone.notes = None
    db_session.flush()

    assert remove_old_details(db_session, NOW) == 2

    db_session.refresh(abandoned)
    db_session.refresh(phone)
    assert abandoned.customer_name is None
    assert abandoned.car_registration is None
    assert abandoned.details_removed_at == NOW
    assert phone.customer_email is None
    assert phone.customer_name == "removed"


def test_blanked_confirmed_booking_is_valid(db_session: Session) -> None:
    seed(db_session)
    booking = old_booking(db_session, status="confirmed")  # never marked completed

    remove_old_details(db_session, NOW)  # flushes and commits: the database rules hold

    db_session.refresh(booking)
    assert booking.status == "confirmed"
    assert booking.customer_name == "removed"


def test_second_run_changes_nothing(db_session: Session) -> None:
    seed(db_session)
    old_booking(db_session)
    make_enquiry(db_session, created_at=OLD)

    assert remove_old_details(db_session, NOW) == 2
    assert remove_old_details(db_session, NOW + timedelta(days=1)) == 0


def test_staff_booking_detail_shows_removed(staff_client: TestClient, db_session: Session) -> None:
    seed(db_session)
    booking = old_booking(db_session)
    remove_old_details(db_session, NOW)

    response = staff_client.get(f"/api/staff/bookings/{booking.reference}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["customer_name"] == "removed"
    assert body["registration"] == "REMOVED"
