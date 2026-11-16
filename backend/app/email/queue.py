"""Queue an email for the worker to send. The row is added in the caller's transaction, so an
email is queued if and only if the change it's about is committed."""

from sqlalchemy.orm import Session

from app.email.message import EmailTemplate, StaffTemplate
from app.models import Booking, EmailLog, StaffUser


def queue_email(session: Session, template: EmailTemplate, booking: Booking) -> EmailLog | None:
    """Add a queued email for this booking. Flushes, doesn't commit. A booking with no email
    (a phone booking can have none) gets nothing, and that's not an error."""
    if booking.customer_email is None:
        return None
    email = EmailLog(template=template, booking=booking, recipient=booking.customer_email)
    session.add(email)
    session.flush()
    return email


def queue_staff_email(session: Session, template: StaffTemplate, user: StaffUser) -> EmailLog:
    """Add a queued account email for a staff member. Flushes, doesn't commit. The worker
    makes the link's token when it sends it."""
    email = EmailLog(template=template, staff_user=user, recipient=user.email)
    session.add(email)
    session.flush()
    return email
