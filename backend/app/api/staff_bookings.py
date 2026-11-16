"""Staff actions on bookings: phone bookings now; detail, move, cancel and status next."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import AfterValidator, AwareDatetime, BaseModel

from app.api.validation import reject, resolve_services
from app.bookings.rules import (
    clean_email,
    clean_make_or_model,
    clean_name,
    clean_notes,
    clean_phone,
    clean_registration,
)
from app.repositories.reservations import SlotUnavailable
from app.schedule.phone import PhoneDetails, create_phone_booking
from app.staff.deps import NowDep, SessionDep, StaffDep, check_origin, current_staff

router = APIRouter(prefix="/staff", dependencies=[Depends(check_origin), Depends(current_staff)])

TAKEN = "That time has just been taken"


def clean_optional_email(value: str | None) -> str | None:
    """Blank means no email: a phone customer may not have one."""
    if value is None or not value.strip():
        return None
    return clean_email(value)


class PhoneBookingIn(BaseModel):
    services: list[str]
    start: AwareDatetime
    bay_id: int
    name: Annotated[str, AfterValidator(clean_name)]
    phone: Annotated[str, AfterValidator(clean_phone)]
    email: Annotated[str | None, AfterValidator(clean_optional_email)] = None
    registration: Annotated[str, AfterValidator(clean_registration)]
    make: Annotated[str, AfterValidator(clean_make_or_model)]
    model: Annotated[str, AfterValidator(clean_make_or_model)]
    notes: Annotated[str | None, AfterValidator(clean_notes)] = None


class CreatedOut(BaseModel):
    reference: str


@router.post("/bookings", status_code=201)
def create_booking(
    body: PhoneBookingIn, staff: StaffDep, session: SessionDep, now: NowDep
) -> CreatedOut:
    """Book a customer who phoned. Any active service, needs-approval ones included: staff
    booking it is the approval."""
    services = resolve_services(session, body.services)
    if len({service.required_bay_type_id for service in services}) > 1:
        raise reject("These services can't be booked together — please book them separately")
    if body.start < now:
        raise reject("That time has already passed")
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
        booking = create_phone_booking(
            session, staff, services, body.start, body.bay_id, details, now
        )
    except SlotUnavailable as error:
        session.rollback()
        raise HTTPException(status_code=409, detail=TAKEN) from error
    session.commit()
    return CreatedOut(reference=booking.reference)
