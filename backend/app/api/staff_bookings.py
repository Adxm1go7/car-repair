"""Staff actions on bookings: phone bookings, the booking page, move, cancel and status, and
answering online requests (the queue, approve, propose another time, decline)."""

import logging
from collections.abc import Sequence
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
from app.models import AuditEntry, Booking, Enquiry, Service
from app.payments.deps import get_payment_provider
from app.payments.provider import PaymentProvider, PaymentUnavailable
from app.repositories.availability import (
    SettingsUnavailable,
    load_free_cancellation_hours,
    load_policy,
)
from app.repositories.bookings import expired_hold
from app.repositories.reservations import SlotUnavailable
from app.schedule.approvals import approve_booking, decline_booking, propose_booking
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


def check_new_booking(services: Sequence[Service], start: datetime, now: datetime) -> None:
    """What every staff-made booking must be: one kind of bay, and not in the past."""
    if len({service.required_bay_type_id for service in services}) > 1:
        raise reject("These services can't be booked together — please book them separately")
    if start < now:
        raise reject("That time has already passed")


class CreatedOut(BaseModel):
    reference: str


@router.post("/bookings", status_code=201)
def create_booking(
    body: PhoneBookingIn, staff: StaffDep, session: SessionDep, now: NowDep
) -> CreatedOut:
    """Book a customer who phoned. Any active service, needs-approval ones included: staff
    booking it is the approval."""
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
    # A request: when it must be answered by. An approval: when the deposit is due by.
    deadline: str | None
    enquiry_id: int | None  # the enquiry this booking was made from
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


def zone_or_503(session: Session) -> ZoneInfo:
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


def _history_text(entry: AuditEntry, zone: ZoneInfo, source: str) -> str:
    who = entry.staff_user.name if entry.staff_user is not None else "Setup"
    before, after = entry.before or {}, entry.after or {}
    if entry.action == "booking.create":
        how = "from an enquiry" if source == "enquiry" else "by phone"
        text = f"Booked {how} by {who}"
    elif entry.action == "booking.move":
        was = datetime.fromisoformat(before["start"])
        text = f"Moved from {format_moment(was, zone).replace(',', '')} by {who}"
    elif entry.action == "booking.cancel":
        text = f"Cancelled by {who}"
    elif entry.action == "booking.status":
        text = f"{STATUS_TEXT.get(after.get('status', ''), 'Status changed')} by {who}"
    elif entry.action == "booking.approve":
        text = f"Approved by {who}"
    elif entry.action == "booking.propose":
        text = f"New time proposed by {who}"
    elif entry.action == "booking.decline":
        text = f"Declined by {who}"
    else:
        text = f"{entry.action} by {who}"
    return f'{text} — "{entry.reason}"' if entry.reason else text


def staff_booking_out(
    session: Session, booking: Booking, now: datetime, zone: ZoneInfo
) -> StaffBookingOut:
    entries = session.scalars(
        select(AuditEntry)
        .where(AuditEntry.booking_reference == booking.reference)
        # Booking an enquiry in is told by its booking.create line; the enquiry's own entry
        # carries the reference for the audit page only.
        .where(AuditEntry.action != "enquiry.approve")
        .options(selectinload(AuditEntry.staff_user))
        .order_by(AuditEntry.at, AuditEntry.id)
    )
    history = [
        HistoryOut(at=local_iso(e.at, zone), text=_history_text(e, zone, booking.source))
        for e in entries
    ]
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
        deadline=local_iso(booking.hold_expires_at, zone)
        if booking.status in ("pending_approval", "awaiting_deposit")
        and booking.hold_expires_at is not None
        else None,
        enquiry_id=session.scalar(select(Enquiry.id).where(Enquiry.booking_id == booking.id)),
        actions=booking_actions(booking.status, booking.start_at, booking.status_changed_at, now),
        starts_on_another_day=starts_on_another_day(booking.start_at, now, zone),
        history=history,
    )


@router.get("/bookings/{reference}")
def booking_detail(reference: str, session: SessionDep, now: NowDep) -> StaffBookingOut:
    zone = zone_or_503(session)
    return staff_booking_out(session, _find(session, reference), now, zone)


@router.get("/bookings/{reference}/move-options")
def move_options(
    reference: str,
    session: SessionDep,
    now: NowDep,
    day: Annotated[date, Query(alias="date")],
) -> StaffAvailabilityOut:
    """Where this booking could go on `day`: its own time isn't counted as taken."""
    zone = zone_or_503(session)
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
    zone = zone_or_503(session)
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
    zone = zone_or_503(session)
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
    zone = zone_or_503(session)
    try:
        booking = change_status(session, staff, reference, body.action, now)
    except LookupError as error:
        raise NOT_FOUND from error
    except NotAllowed as error:
        raise _refused(session, error.detail) from error
    session.commit()
    return staff_booking_out(session, booking, now, zone)


# --- requests ------------------------------------------------------------------------


class RequestOut(BaseModel):
    reference: str
    customer_name: str | None
    services: list[str]
    start: str
    bay: str
    deadline: str
    created_at: str


@router.get("/requests")
def requests(session: SessionDep, now: NowDep) -> list[RequestOut]:
    """Requests waiting for an answer, oldest first. One past its deadline is left out: it
    has already lapsed, and the worker is about to release it."""
    zone = zone_or_503(session)
    waiting = session.scalars(
        select(Booking)
        .where(Booking.status == "pending_approval", ~expired_hold(now))
        .options(selectinload(Booking.items), selectinload(Booking.reservation))
        .order_by(Booking.created_at, Booking.id)
    )
    return [
        RequestOut(
            reference=booking.reference,
            customer_name=booking.customer_name,
            services=[item.service_name for item in booking.items],
            start=local_iso(booking.start_at, zone),
            bay=booking.reservation.bay.name,
            deadline=local_iso(booking.hold_expires_at or now, zone),
            created_at=local_iso(booking.created_at, zone),
        )
        for booking in waiting
    ]


def _settings_or_503(error: SettingsUnavailable) -> HTTPException:
    return HTTPException(status_code=503, detail="Bookings unavailable")


@router.post("/bookings/{reference}/approve")
def approve(reference: str, staff: StaffDep, session: SessionDep, now: NowDep) -> StaffBookingOut:
    zone = zone_or_503(session)
    try:
        booking = approve_booking(session, staff, reference, now)
    except LookupError as error:
        raise NOT_FOUND from error
    except NotAllowed as error:
        raise _refused(session, error.detail) from error
    except SettingsUnavailable as error:
        session.rollback()
        raise _settings_or_503(error) from error
    session.commit()
    return staff_booking_out(session, booking, now, zone)


@router.post("/bookings/{reference}/propose")
def propose(
    reference: str,
    body: MoveIn,
    staff: StaffDep,
    session: SessionDep,
    now: NowDep,
    provider: ProviderDep,
) -> StaffBookingOut:
    """Move a request (or an unpaid approval) to a time agreed on the phone, and ask for
    the deposit for it."""
    zone = zone_or_503(session)
    try:
        booking = propose_booking(
            session, provider, staff, reference, body.start, body.bay_id, body.reason, now
        )
    except LookupError as error:
        raise NOT_FOUND from error
    except NotAllowed as error:
        raise _refused(session, error.detail) from error
    except SlotUnavailable as error:
        raise _refused(session, "taken") from error
    except SettingsUnavailable as error:
        session.rollback()
        raise _settings_or_503(error) from error
    except PaymentUnavailable as error:
        session.rollback()
        log.warning("propose for %s: payment provider failed: %s", reference, error)
        raise HTTPException(status_code=503, detail="We couldn't change it just now") from error
    session.commit()
    return staff_booking_out(session, booking, now, zone)


@router.post("/bookings/{reference}/decline")
def decline(
    reference: str, body: CancelIn, staff: StaffDep, session: SessionDep, now: NowDep
) -> StaffBookingOut:
    zone = zone_or_503(session)
    try:
        booking = decline_booking(session, staff, reference, body.reason, now)
    except LookupError as error:
        raise NOT_FOUND from error
    except NotAllowed as error:
        raise _refused(session, error.detail) from error
    session.commit()
    return staff_booking_out(session, booking, now, zone)
