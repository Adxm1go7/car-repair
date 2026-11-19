"""What happens to an enquiry: the customer sends it; staff book it in or decline it.
Nothing here commits."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.email.queue import queue_enquiry_email
from app.models import Enquiry, Service, StaffUser
from app.schedule.phone import PhoneDetails, create_phone_booking
from app.staff.audit import record_audit


class EnquiryNotNew(Exception):
    """Someone has already booked in or declined this enquiry."""


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


def _locked_new(session: Session, enquiry_id: int) -> Enquiry:
    """The enquiry, locked until the transaction ends, so two staff can't both handle it.
    Locked before anything else (reserve's locks come after)."""
    enquiry = session.get(Enquiry, enquiry_id, with_for_update=True, populate_existing=True)
    if enquiry is None:
        raise LookupError(enquiry_id)
    if enquiry.status != "new":
        raise EnquiryNotNew(enquiry_id)
    return enquiry


def approve_enquiry(
    session: Session,
    staff: StaffUser,
    enquiry_id: int,
    services: Sequence[Service],
    start: datetime,
    bay_id: int,
    details: PhoneDetails,
    now: datetime,
) -> Enquiry:
    """Book the enquiry in: a confirmed booking with no deposit, made the phone-booking way,
    and linked here. Raises LookupError, EnquiryNotNew, or SlotUnavailable (the caller rolls
    back, and the enquiry stays new)."""
    enquiry = _locked_new(session, enquiry_id)
    booking = create_phone_booking(
        session, staff, services, start, bay_id, details, now, source="enquiry"
    )
    enquiry.status = "converted"
    enquiry.booking = booking
    enquiry.handled_at = now
    enquiry.handled_by = staff.id
    session.flush()
    record_audit(
        session,
        staff,
        "enquiry.approve",
        "enquiry",
        enquiry.id,
        after={"status": "converted", "booking": booking.reference},
        booking_reference=booking.reference,
        now=now,
    )
    return enquiry


def decline_enquiry(
    session: Session, staff: StaffUser, enquiry_id: int, reason: str | None, now: datetime
) -> Enquiry:
    """Decline the enquiry and email the customer, with the reason if there is one. Raises
    LookupError or EnquiryNotNew."""
    staff_id = staff.id  # read first: loading it mid-change would flush a half-made row
    enquiry = _locked_new(session, enquiry_id)
    enquiry.status = "declined"
    enquiry.decline_reason = reason
    enquiry.handled_at = now
    enquiry.handled_by = staff_id
    session.flush()
    queue_enquiry_email(session, "enquiry_declined", enquiry, {"reason": reason})
    record_audit(
        session,
        staff,
        "enquiry.decline",
        "enquiry",
        enquiry.id,
        after={"status": "declined"},
        reason=reason,
        now=now,
    )
    return enquiry
