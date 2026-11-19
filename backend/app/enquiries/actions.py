"""What happens to an enquiry: the customer sends it; staff book it in or decline it.
Nothing here commits."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.email.queue import queue_enquiry_email
from app.models import Enquiry


@dataclass(frozen=True)
class EnquiryDetails:
    """Already cleaned by the `clean_*` rules."""

    name: str
    phone: str
    email: str
    registration: str
    make: str
    model: str
    description: str


def create_enquiry(session: Session, details: EnquiryDetails, now: datetime) -> Enquiry:
    """Record a new enquiry and queue the "we've got it" email."""
    enquiry = Enquiry(
        status="new",
        created_at=now,
        customer_name=details.name,
        customer_phone=details.phone,
        customer_email=details.email,
        car_registration=details.registration,
        car_make=details.make,
        car_model=details.model,
        description=details.description,
    )
    session.add(enquiry)
    session.flush()
    queue_enquiry_email(session, "enquiry_received", enquiry)
    return enquiry
