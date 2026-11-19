"""Staff routes for enquiries: the New, Booked and Declined lists, one enquiry, book it in
(the phone-booking way) and decline it."""

from datetime import datetime
from typing import Annotated, Final, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import AfterValidator, BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.holds import local_iso
from app.api.staff_bookings import TAKEN, CancelIn, PhoneBookingIn, check_new_booking, zone_or_503
from app.api.validation import ResourceId, resolve_services
from app.bookings.rules import clean_email
from app.enquiries.actions import EnquiryNotNew, approve_enquiry, decline_enquiry
from app.models import Enquiry
from app.repositories.reservations import SlotUnavailable
from app.schedule.phone import PhoneDetails
from app.staff.deps import NowDep, SessionDep, StaffDep, check_origin, current_staff

router = APIRouter(prefix="/staff", dependencies=[Depends(check_origin), Depends(current_staff)])

NOT_FOUND: Final = HTTPException(status_code=404, detail="No such enquiry")
HANDLED_LIMIT: Final = 100  # the latest handled ones; there's no paging
SUMMARY_LENGTH: Final = 80

EnquiryStatus = Literal["new", "converted", "declined"]
EnquiryAction = Literal["approve", "decline"]


class EnquiryRowOut(BaseModel):
    id: int
    status: str
    customer_name: str
    registration: str
    make: str
    model: str
    summary: str  # the description's first line, cut short
    created_at: str
    handled_at: str | None


class StaffEnquiryOut(BaseModel):
    id: int
    status: str
    customer_name: str
    customer_phone: str
    customer_email: str
    registration: str
    make: str
    model: str
    description: str
    created_at: str
    handled_at: str | None
    handled_by: str | None  # their name
    decline_reason: str | None
    booking_reference: str | None
    actions: list[EnquiryAction]


class EnquiryApproveIn(PhoneBookingIn):
    """A phone booking's body, but the email is required: the confirmation goes by email."""

    email: Annotated[str, AfterValidator(clean_email)]


def _summary(description: str) -> str:
    lines = description.splitlines()
    return lines[0][:SUMMARY_LENGTH] if lines else ""


def _iso(value: datetime | None, session: Session) -> str | None:
    return local_iso(value, zone_or_503(session)) if value is not None else None


@router.get("/enquiries")
def enquiries(session: SessionDep, status: EnquiryStatus = "new") -> list[EnquiryRowOut]:
    """New ones oldest first (the queue); handled ones newest first, the latest 100."""
    query = select(Enquiry).where(Enquiry.status == status)
    if status == "new":
        query = query.order_by(Enquiry.created_at, Enquiry.id)
    else:
        query = query.order_by(Enquiry.handled_at.desc(), Enquiry.id.desc()).limit(HANDLED_LIMIT)
    zone = zone_or_503(session)
    return [
        EnquiryRowOut(
            id=e.id,
            status=e.status,
            customer_name=e.customer_name,
            registration=e.car_registration,
            make=e.car_make,
            model=e.car_model,
            summary=_summary(e.description),
            created_at=local_iso(e.created_at, zone),
            handled_at=local_iso(e.handled_at, zone) if e.handled_at is not None else None,
        )
        for e in session.scalars(query)
    ]


def _out(session: Session, enquiry: Enquiry) -> StaffEnquiryOut:
    return StaffEnquiryOut(
        id=enquiry.id,
        status=enquiry.status,
        customer_name=enquiry.customer_name,
        customer_phone=enquiry.customer_phone,
        customer_email=enquiry.customer_email,
        registration=enquiry.car_registration,
        make=enquiry.car_make,
        model=enquiry.car_model,
        description=enquiry.description,
        created_at=local_iso(enquiry.created_at, zone_or_503(session)),
        handled_at=_iso(enquiry.handled_at, session),
        handled_by=enquiry.handler.name if enquiry.handler is not None else None,
        decline_reason=enquiry.decline_reason,
        booking_reference=enquiry.booking.reference if enquiry.booking is not None else None,
        actions=["approve", "decline"] if enquiry.status == "new" else [],
    )


def _find(session: Session, enquiry_id: ResourceId) -> Enquiry:
    enquiry = session.scalars(
        select(Enquiry)
        .where(Enquiry.id == enquiry_id)
        .options(selectinload(Enquiry.handler), selectinload(Enquiry.booking))
        .execution_options(populate_existing=True)
    ).one_or_none()
    if enquiry is None:
        raise NOT_FOUND
    return enquiry


@router.get("/enquiries/{enquiry_id}")
def enquiry_detail(enquiry_id: ResourceId, session: SessionDep) -> StaffEnquiryOut:
    return _out(session, _find(session, enquiry_id))


def _refused(session: Session, status: int, detail: str) -> HTTPException:
    session.rollback()
    return HTTPException(status_code=status, detail=detail)


@router.post("/enquiries/{enquiry_id}/approve")
def approve(
    enquiry_id: ResourceId,
    body: EnquiryApproveIn,
    staff: StaffDep,
    session: SessionDep,
    now: NowDep,
) -> StaffEnquiryOut:
    """Book the enquiry in: a confirmed booking with no deposit; the customer is emailed."""
    services = resolve_services(session, body.services)
    check_new_booking(services, body.start, now)
    details = PhoneDetails(
        name=body.name,
        phone=body.phone,
        email=body.email,
        registration=body.registration,
        make=body.make,
        model=body.model,
        notes=body.notes,
    )
    try:
        approve_enquiry(session, staff, enquiry_id, services, body.start, body.bay_id, details, now)
    except LookupError as error:
        raise _refused(session, 404, "No such enquiry") from error
    except EnquiryNotNew as error:
        raise _refused(session, 409, "not_new") from error
    except SlotUnavailable as error:
        raise _refused(session, 409, TAKEN) from error
    session.commit()
    return _out(session, _find(session, enquiry_id))


@router.post("/enquiries/{enquiry_id}/decline")
def decline(
    enquiry_id: ResourceId, body: CancelIn, staff: StaffDep, session: SessionDep, now: NowDep
) -> StaffEnquiryOut:
    try:
        decline_enquiry(session, staff, enquiry_id, body.reason, now)
    except LookupError as error:
        raise _refused(session, 404, "No such enquiry") from error
    except EnquiryNotNew as error:
        raise _refused(session, 409, "not_new") from error
    session.commit()
    return _out(session, _find(session, enquiry_id))
