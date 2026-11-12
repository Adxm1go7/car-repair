"""Public booking: hold a slot while the customer types their details."""

from datetime import datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import AwareDatetime, BaseModel
from sqlalchemy.orm import Session

from app.api.validation import check_bookable_date, reject, resolve_services
from app.bookings.service import create_hold, summary_services
from app.clock import utc_now
from app.db import get_session
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
