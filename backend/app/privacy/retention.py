"""The 12-month rule: a booking's or enquiry's customer details are blanked a year on.

The rows stay, so the schedule's history, the counts and the audit trail stay whole; only
the personal details go. Placeholders, not NULLs, so the database rules (a confirmed booking
has details, enquiry columns are NOT NULL) still hold. A field is only replaced where it was
set: an abandoned hold that never got details keeps its NULLs.

Copies of the details go too: the customer fields inside audit entries (a phone booking's
`booking.create` stores them all), the staff-typed audit reasons and decline reasons, and the
email log's recipient, context and error text. A queued email is skipped (it can't still be
waiting after a year, but it would need its recipient if it were).
"""

from datetime import datetime, timedelta
from typing import Any, Final

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import AuditEntry, Booking, EmailLog, Enquiry
from app.models.booking import WAITING_STATUSES

RETAIN_FOR: Final = timedelta(days=365)
RETENTION_INTERVAL: Final = timedelta(hours=24)
REMOVED: Final = "removed"
REMOVED_REGISTRATION: Final = "REMOVED"  # fits the 8-character registration column

# Customer fields as they appear inside audit entries' `before` and `after`.
AUDIT_KEYS: Final = frozenset(
    {
        "name",
        "phone",
        "email",
        "registration",
        "notes",
        "description",
        "customer_name",
        "customer_phone",
        "customer_email",
        "car_registration",
    }
)


def _placeholder(value: str | None, placeholder: str = REMOVED) -> str | None:
    return None if value is None else placeholder


def _blank_snapshot(snapshot: dict[str, Any] | None) -> dict[str, Any] | None:
    if snapshot is None:
        return None
    # A new dict, so SQLAlchemy sees the JSONB change.
    return {k: REMOVED if k in AUDIT_KEYS and v is not None else v for k, v in snapshot.items()}


def _blank_audit(session: Session, *conditions: Any) -> None:
    for entry in session.scalars(select(AuditEntry).where(or_(*conditions)).with_for_update()):
        entry.before = _blank_snapshot(entry.before)
        entry.after = _blank_snapshot(entry.after)
        entry.reason = _placeholder(entry.reason)


def _blank_emails(session: Session, condition: Any) -> None:
    emails = select(EmailLog).where(condition, EmailLog.status != "queued").with_for_update()
    for email in session.scalars(emails):
        email.recipient = REMOVED
        email.context = None
        email.last_error = None


def _blank_booking(session: Session, booking: Booking, now: datetime) -> None:
    booking.customer_name = _placeholder(booking.customer_name)
    booking.customer_phone = _placeholder(booking.customer_phone)
    booking.customer_email = _placeholder(booking.customer_email)
    booking.car_registration = _placeholder(booking.car_registration, REMOVED_REGISTRATION)
    booking.notes = None
    booking.details_removed_at = now
    _blank_audit(
        session,
        (AuditEntry.entity_type == "booking") & (AuditEntry.entity_id == booking.id),
        AuditEntry.booking_reference == booking.reference,
    )
    _blank_emails(session, EmailLog.booking_id == booking.id)


def _blank_enquiry(session: Session, enquiry: Enquiry, now: datetime) -> None:
    enquiry.customer_name = REMOVED
    enquiry.customer_phone = REMOVED
    enquiry.customer_email = REMOVED
    enquiry.car_registration = REMOVED_REGISTRATION
    enquiry.description = REMOVED
    enquiry.decline_reason = _placeholder(enquiry.decline_reason)
    enquiry.details_removed_at = now
    _blank_audit(
        session, (AuditEntry.entity_type == "enquiry") & (AuditEntry.entity_id == enquiry.id)
    )
    _blank_emails(session, EmailLog.enquiry_id == enquiry.id)


def remove_old_details(session: Session, now: datetime) -> int:
    """Blank every booking that ended more than RETAIN_FOR ago (unless it's still waiting
    for someone) and every enquiry older than that which wasn't booked in; an enquiry that was
    booked in follows its booking. Commits, and returns how many rows were blanked."""
    cutoff = now - RETAIN_FOR
    bookings = session.scalars(
        select(Booking)
        .where(
            Booking.end_at < cutoff,
            Booking.details_removed_at.is_(None),
            Booking.status.not_in(WAITING_STATUSES),
        )
        .order_by(Booking.id)
        .with_for_update()
    ).all()
    for booking in bookings:
        _blank_booking(session, booking, now)
    session.flush()

    enquiries = session.scalars(
        select(Enquiry)
        .outerjoin(Booking, Enquiry.booking_id == Booking.id)
        .where(
            Enquiry.details_removed_at.is_(None),
            or_(
                Enquiry.status.in_(("new", "declined")) & (Enquiry.created_at < cutoff),
                (Enquiry.status == "converted") & Booking.details_removed_at.is_not(None),
            ),
        )
        .order_by(Enquiry.id)
        .with_for_update(of=Enquiry)
    ).all()
    for enquiry in enquiries:
        _blank_enquiry(session, enquiry, now)
    session.commit()
    return len(bookings) + len(enquiries)
