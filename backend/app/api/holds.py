"""Public booking: hold a slot while the customer types their details."""

from datetime import datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import AfterValidator, AwareDatetime, BaseModel, StringConstraints
from sqlalchemy.orm import Session

from app.api.validation import check_bookable_date, reject, resolve_services
from app.bookings.rules import (
    clean_email,
    clean_make_or_model,
    clean_name,
    clean_notes,
    clean_phone,
    clean_registration,
)
from app.bookings.service import (
    AlreadyConfirmed,
    CustomerDetails,
    HoldExpired,
    HoldNotFound,
    cancel_hold,
    confirm_hold,
    create_hold,
    summary_services,
)
from app.clock import utc_now
from app.db import get_session
from app.models import Booking
from app.repositories.availability import (
    SettingsUnavailable,
    load_booking_window_days,
    load_hold_minutes,
    load_policy,
)
from app.repositories.reservations import SlotUnavailable

router = APIRouter()

SessionDep = Annotated[Session, Depends(get_session)]
NowDep = Annotated[datetime, Depends(utc_now)]

TAKEN = "That time has just been taken"


def local_iso(value: datetime, zone: ZoneInfo) -> str:
    """Garage-local ISO time with its offset, like availability: "+00:00", never "Z"."""
    return value.astimezone(zone).isoformat()


class HoldIn(BaseModel):
    services: list[str]
    start: AwareDatetime


class ServiceSummaryOut(BaseModel):
    slug: str
    name: str
    duration_minutes: int
    price_from_pence: int
    price_to_pence: int | None


class HoldOut(BaseModel):
    reference: str
    hold_token: str
    expires_at: str
    expires_in_seconds: int
    start: str
    end: str
    services: list[ServiceSummaryOut]


@router.post("/holds", status_code=201)
def hold(body: HoldIn, session: SessionDep, now: NowDep) -> HoldOut:
    """Hold `start` for these services. Only the returned `hold_token` can confirm it."""
    try:
        policy = load_policy(session)
        window_days = load_booking_window_days(session)
        hold_minutes = load_hold_minutes(session)
    except SettingsUnavailable as error:
        raise HTTPException(status_code=503, detail="Booking unavailable") from error

    services = resolve_services(session, body.services)
    if any(service.approval_mode != "instant" for service in services):
        raise reject("This service needs approval — please call us")
    if len({service.required_bay_type_id for service in services}) > 1:
        raise reject("These services can't be booked together — please book them separately")
    check_bookable_date(body.start.astimezone(policy.zone).date(), now, policy.zone, window_days)

    try:
        created = create_hold(session, services, body.start, now, hold_minutes)
    except SlotUnavailable as error:
        raise HTTPException(status_code=409, detail=TAKEN) from error
    booking = created.booking
    response = HoldOut(
        reference=booking.reference,
        hold_token=created.token,
        expires_at=local_iso(booking.hold_expires_at or now, policy.zone),
        expires_in_seconds=hold_minutes * 60,
        start=local_iso(booking.start_at, policy.zone),
        end=local_iso(booking.end_at, policy.zone),
        services=[ServiceSummaryOut.model_validate(s) for s in summary_services(booking)],
    )
    session.commit()
    return response


# --- confirm and release -----------------------------------------------------------

Token = Annotated[str, StringConstraints(min_length=1, max_length=100)]
REFERENCE_LENGTH = 9  # XXXX-XXXX


class ConfirmIn(BaseModel):
    hold_token: Token
    name: Annotated[str, AfterValidator(clean_name)]
    phone: Annotated[str, AfterValidator(clean_phone)]
    email: Annotated[str, AfterValidator(clean_email)]
    registration: Annotated[str, AfterValidator(clean_registration)]
    make: Annotated[str, AfterValidator(clean_make_or_model)]
    model: Annotated[str, AfterValidator(clean_make_or_model)]
    notes: Annotated[str | None, AfterValidator(clean_notes)] = None


class CancelIn(BaseModel):
    hold_token: Token


class BookingSummaryOut(BaseModel):
    reference: str
    status: str
    start: str
    end: str
    services: list[ServiceSummaryOut]
    registration: str
    make: str
    model: str


NOT_FOUND = HTTPException(status_code=404, detail="Booking not found")


def _check_reference(reference: str) -> None:
    """Refuse a reference no booking could have, before it reaches the database."""
    if len(reference) > REFERENCE_LENGTH or "\x00" in reference:
        raise NOT_FOUND


def _summary(booking: Booking, zone: ZoneInfo) -> BookingSummaryOut:
    return BookingSummaryOut(
        reference=booking.reference,
        status=booking.status,
        start=local_iso(booking.start_at, zone),
        end=local_iso(booking.end_at, zone),
        services=[ServiceSummaryOut.model_validate(s) for s in summary_services(booking)],
        registration=booking.car_registration or "",
        make=booking.car_make or "",
        model=booking.car_model or "",
    )


@router.post("/holds/{reference}/confirm")
def confirm(reference: str, body: ConfirmIn, session: SessionDep, now: NowDep) -> BookingSummaryOut:
    """Attach the customer's details and confirm. A repeat with the same token is harmless."""
    _check_reference(reference)
    try:
        zone = load_policy(session).zone
    except SettingsUnavailable as error:
        raise HTTPException(status_code=503, detail="Booking unavailable") from error
    details = CustomerDetails(
        name=body.name,
        phone=body.phone,
        email=body.email,
        registration=body.registration,
        make=body.make,
        model=body.model,
        notes=body.notes,
    )
    try:
        booking = confirm_hold(session, reference, body.hold_token, details, now)
    except HoldNotFound as error:
        raise NOT_FOUND from error
    except HoldExpired as error:
        session.commit()  # keep the release confirm_hold just made
        raise HTTPException(status_code=410, detail="Your hold has expired") from error
    response = _summary(booking, zone)
    session.commit()
    return response


@router.delete("/holds/{reference}", status_code=204)
def cancel(reference: str, body: CancelIn, session: SessionDep) -> None:
    """Give the slot back, for "Change time". Releasing an expired hold again is harmless."""
    _check_reference(reference)
    try:
        cancel_hold(session, reference, body.hold_token)
    except HoldNotFound as error:
        raise NOT_FOUND from error
    except AlreadyConfirmed as error:
        raise HTTPException(status_code=409, detail="This booking is already confirmed") from error
    session.commit()
