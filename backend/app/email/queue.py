"""Queue an email for the worker to send. The row is added in the caller's transaction, so an
email is queued if and only if the change it's about is committed."""

from sqlalchemy.orm import Session

from app.email.message import EmailTemplate
from app.models import Booking, EmailLog


def queue_email(session: Session, template: EmailTemplate, booking: Booking) -> EmailLog:
    """Add a queued email for this booking. Flushes, doesn't commit."""
    if booking.customer_email is None:
        raise ValueError(f"booking {booking.reference} has no customer email")
    email = EmailLog(template=template, booking=booking, recipient=booking.customer_email)
    session.add(email)
    session.flush()
    return email
