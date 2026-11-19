"""Queue an email for the worker to send. The row is added in the caller's transaction, so an
email is queued if and only if the change it's about is committed."""

from typing import Any

from sqlalchemy.orm import Session

from app.email.message import EmailTemplate, EnquiryTemplate, StaffTemplate
from app.models import Booking, EmailLog, Enquiry, StaffUser


def queue_email(
    session: Session,
    template: EmailTemplate,
    booking: Booking,
    context: dict[str, Any] | None = None,
) -> EmailLog | None:
    """Add a queued email for this booking. Flushes, doesn't commit. A booking with no email
    (a phone booking can have none) gets nothing, and that's not an error. `context` is
    what the email needs that the booking won't say any more: never a token."""
    if booking.customer_email is None:
        return None
    email = EmailLog(
        template=template, booking=booking, recipient=booking.customer_email, context=context
    )
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


def queue_enquiry_email(
    session: Session,
    template: EnquiryTemplate,
    enquiry: Enquiry,
    context: dict[str, Any] | None = None,
) -> EmailLog:
    """Add a queued email about an enquiry. Flushes, doesn't commit. An enquiry always has an
    email address."""
    email = EmailLog(
        template=template, enquiry=enquiry, recipient=enquiry.customer_email, context=context
    )
    session.add(email)
    session.flush()
    return email
