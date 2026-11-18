"""Staff actions on bookings: phone bookings, the booking page, move, cancel and status."""

import logging
from datetime import date, datetime
from typing import Annotated, Final
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import AfterValidator, AwareDatetime, BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.holds import REFERENCE_LENGTH, local_iso
from app.api.staff_schedule import StaffAvailabilityOut, StaffSlotOut
from app.api.validation import reject, resolve_services
from app.bookings.rules import (
    clean_email,
    clean_make_or_model,
    clean_name,
    clean_notes,
    clean_phone,
    clean_registration,
)
from app.email.render import format_moment
from app.models import AuditEntry, Booking
from app.payments.deps import get_payment_provider
from app.payments.provider import PaymentProvider, PaymentUnavailable
from app.repositories.availability import (
    SettingsUnavailable,
    load_free_cancellation_hours,
    load_policy,
)
from app.repositories.reservations import SlotUnavailable
from app.schedule.availability import infos_for_booking, staff_free_times
from app.schedule.changes import NotAllowed, change_status, garage_cancel, move_booking
from app.schedule.phone import PhoneDetails, create_phone_booking
from app.schedule.status_rules import Action, StatusAction, booking_actions, starts_on_another_day
from app.staff.deps import NowDep, SessionDep, StaffDep, check_origin, current_staff

router = APIRouter(prefix="/staff", dependencies=[Depends(check_origin), Depends(current_staff)])

log = logging.getLogger("uvicorn.error")
ProviderDep = Annotated[PaymentProvider, Depends(get_payment_provider)]

TAKEN = "That time has just been taken"
NOT_FOUND: Final = HTTPException(status_code=404, detail="No such booking")
STATUS_TEXT: Final[dict[str, str]] = {
    "in_progress": "Started the job",
    "completed": "Completed the job",
    "no_show": "Marked as a no show",
    "confirmed": "Set back to confirmed",
}


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


# --- the booking page ------------------------------------------------------------


def clean_reason(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    value = value.strip()
    if len(value) > 500:
        raise ValueError("The reason can be at most 500 characters")
    return value


Reason = Annotated[str | None, AfterValidator(clean_reason)]


class BayRefOut(BaseModel):
    id: int
    name: str


class HistoryOut(BaseModel):
    at: str
    text: str


class StaffBookingOut(BaseModel):
    reference: str
    status: str
    source: str
    start: str
    end: str
    bay: BayRefOut
    services: list[str]
    registration: str | None
    make: str | None
    model: str | None
    customer_name: str | None
    customer_phone: str | None
    customer_email: str | None
    notes: str | None
    deposit_status: str
    actions: list[Action]
    starts_on_another_day: bool
    history: list[HistoryOut]


class MoveIn(BaseModel):
    start: AwareDatetime
    bay_id: int
    reason: Reason = None


class CancelIn(BaseModel):
    reason: Reason = None


class StatusIn(BaseModel):
    action: StatusAction


def _zone(session: Session) -> ZoneInfo:
    try:
        return load_policy(session).zone
    except SettingsUnavailable as error:
        raise HTTPException(status_code=503, detail="Bookings unavailable") from error


def _find(session: Session, reference: str) -> Booking:
    if len(reference) > REFERENCE_LENGTH or "\x00" in reference:
        raise NOT_FOUND
    booking = session.scalars(
        select(Booking)
        .where(Booking.reference == reference)
        .options(selectinload(Booking.items), selectinload(Booking.reservation))
    ).one_or_none()
    if booking is None:
        raise NOT_FOUND
    return booking


def _history_text(entry: AuditEntry, zone: ZoneInfo) -> str:
    who = entry.staff_user.name if entry.staff_user is not None else "Setup"
    before, after = entry.before or {}, entry.after or {}
    if entry.action == "booking.create":
        text = f"Booked by phone by {who}"
    elif entry.action == "booking.move":
        was = datetime.fromisoformat(before["start"])
        text = f"Moved from {format_moment(was, zone).replace(',', '')} by {who}"
    elif entry.action == "booking.cancel":
        text = f"Cancelled by {who}"
    elif entry.action == "booking.status":
        text = f"{STATUS_TEXT.get(after.get('status', ''), 'Status changed')} by {who}"
    else:
        text = f"{entry.action} by {who}"
    return f'{text} — "{entry.reason}"' if entry.reason else text


def staff_booking_out(
    session: Session, booking: Booking, now: datetime, zone: ZoneInfo
) -> StaffBookingOut:
    entries = session.scalars(
        select(AuditEntry)
        .where(AuditEntry.booking_reference == booking.reference)
        .options(selectinload(AuditEntry.staff_user))
        .order_by(AuditEntry.at, AuditEntry.id)
    )
    history = [HistoryOut(at=local_iso(e.at, zone), text=_history_text(e, zone)) for e in entries]
    if booking.source == "online" and booking.confirmed_at is not None:
        history.insert(
            0, HistoryOut(at=local_iso(booking.confirmed_at, zone), text="Booked online")
        )
    bay = booking.reservation.bay
    return StaffBookingOut(
        reference=booking.reference,
        status=booking.status,
        source=booking.source,
        start=local_iso(booking.start_at, zone),
        end=local_iso(booking.end_at, zone),
        bay=BayRefOut(id=bay.id, name=bay.name),
        services=[item.service_name for item in booking.items],
        registration=booking.car_registration,
        make=booking.car_make,
        model=booking.car_model,
        customer_name=booking.customer_name,
        customer_phone=booking.customer_phone,
        customer_email=booking.customer_email,
        notes=booking.notes,
        deposit_status=booking.deposit_status,
        actions=booking_actions(booking.status, booking.start_at, booking.status_changed_at, now),
        starts_on_another_day=starts_on_another_day(booking.start_at, now, zone),
        history=history,
    )


@router.get("/bookings/{reference}")
def booking_detail(reference: str, session: SessionDep, now: NowDep) -> StaffBookingOut:
    zone = _zone(session)
    return staff_booking_out(session, _find(session, reference), now, zone)


@router.get("/bookings/{reference}/move-options")
def move_options(
    reference: str,
    session: SessionDep,
    now: NowDep,
    day: Annotated[date, Query(alias="date")],
) -> StaffAvailabilityOut:
    """Where this booking could go on `day`: its own time isn't counted as taken."""
    zone = _zone(session)
    booking = _find(session, reference)
    result = staff_free_times(
        session, infos_for_booking(booking), day, now, exclude_reservation_id=booking.reservation_id
    )
    return StaffAvailabilityOut(
        date=day.isoformat(),
        timezone=zone.key,
        duration_minutes=result.duration_minutes,
        unavailable_reason=result.unavailable_reason,
        slots=[
            StaffSlotOut(start=s.start.isoformat(), end=s.end.isoformat(), bay_ids=list(s.bay_ids))
            for s in result.slots
        ],
    )


def _refused(session: Session, detail: str) -> HTTPException:
    session.rollback()
    return HTTPException(status_code=409, detail=detail)


@router.post("/bookings/{reference}/move")
def move(
    reference: str, body: MoveIn, staff: StaffDep, session: SessionDep, now: NowDep
) -> StaffBookingOut:
    zone = _zone(session)
    try:
        booking = move_booking(session, staff, reference, body.start, body.bay_id, body.reason, now)
    except LookupError as error:
        raise NOT_FOUND from error
    except NotAllowed as error:
        raise _refused(session, error.detail) from error
    except SlotUnavailable as error:
        raise _refused(session, "taken") from error
    session.commit()
    return staff_booking_out(session, booking, now, zone)


@router.post("/bookings/{reference}/cancel")
def cancel(
    reference: str,
    body: CancelIn,
    staff: StaffDep,
    session: SessionDep,
    now: NowDep,
    provider: ProviderDep,
) -> StaffBookingOut:
    zone = _zone(session)
    hours = load_free_cancellation_hours(session)
    try:
        booking = garage_cancel(session, provider, staff, reference, body.reason, now, hours)
    except LookupError as error:
        raise NOT_FOUND from error
    except NotAllowed as error:
        raise _refused(session, error.detail) from error
    except PaymentUnavailable as error:
        session.rollback()  # nothing saved: still confirmed, still paid
        log.warning("staff cancel of %s: payment provider failed: %s", reference, error)
        raise HTTPException(status_code=503, detail="We couldn't cancel just now") from error
    session.commit()
    return staff_booking_out(session, booking, now, zone)


@router.post("/bookings/{reference}/status")
def set_status(
    reference: str, body: StatusIn, staff: StaffDep, session: SessionDep, now: NowDep
) -> StaffBookingOut:
    zone = _zone(session)
    try:
        booking = change_status(session, staff, reference, body.action, now)
    except LookupError as error:
        raise NOT_FOUND from error
    except NotAllowed as error:
        raise _refused(session, error.detail) from error
    session.commit()
    return staff_booking_out(session, booking, now, zone)
