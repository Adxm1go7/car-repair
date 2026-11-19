"""Public, read-only catalogue endpoints: services, opening hours, garage details."""

from datetime import datetime, time, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy.orm import Session

from app.clock import utc_now
from app.config import AppConfig
from app.db import get_session
from app.models import Timetable
from app.repositories.availability import (
    SettingsUnavailable,
    load_booking_window_days,
    load_deposit_pence,
    load_hold_minutes,
    load_payment_hold_minutes,
    load_policy,
)
from app.repositories.catalogue import get_setting, list_active_services
from app.repositories.hours import timetables_between, week_of

router = APIRouter()

SessionDep = Annotated[Session, Depends(get_session)]
NowDep = Annotated[datetime, Depends(utc_now)]


class ServiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    slug: str
    name: str
    category: str
    description: str
    duration_minutes: int
    price_from_pence: int
    price_to_pence: int | None
    approval_mode: Literal["instant", "needs_approval"]


class BreakOut(BaseModel):
    start: str
    end: str


class OpeningDayOut(BaseModel):
    weekday: int
    open: str | None
    close: str | None
    breaks: list[BreakOut]


class GarageOut(BaseModel):
    name: str
    address: str
    phone: str
    email: str
    timezone: str


def _hhmm(value: time) -> str:
    return value.strftime("%H:%M")


def week_out(timetable: Timetable) -> list[OpeningDayOut]:
    """A timetable's seven days, Monday first. A weekday with no row is closed."""
    return [
        OpeningDayOut(
            weekday=weekday,
            open=_hhmm(hours.open) if hours.open is not None else None,
            close=_hhmm(hours.close) if hours.close is not None else None,
            breaks=[BreakOut(start=_hhmm(a), end=_hhmm(b)) for a, b in hours.breaks],
        )
        for weekday, hours in week_of(timetable).items()
    ]


@router.get("/services")
def services(session: SessionDep) -> list[ServiceOut]:
    return [ServiceOut.model_validate(service) for service in list_active_services(session)]


class TimetableOut(BaseModel):
    starts_on: str
    days: list[OpeningDayOut]  # always Monday to Sunday


class OpeningHoursOut(BaseModel):
    timetables: list[TimetableOut]


@router.get("/opening-hours")
def opening_hours(session: SessionDep, now: NowDep) -> OpeningHoursOut:
    """The timetable in force today, then any starting within the booking window, oldest
    first. A weekday with no row is reported as closed."""
    try:
        today = now.astimezone(load_policy(session).zone).date()
        last = today + timedelta(days=load_booking_window_days(session))
    except SettingsUnavailable as error:
        raise HTTPException(status_code=503, detail="Opening hours unavailable") from error
    return OpeningHoursOut(
        timetables=[
            TimetableOut(starts_on=timetable.starts_on.isoformat(), days=week_out(timetable))
            for timetable in timetables_between(session, today, last)
        ]
    )


class StripePaymentOut(BaseModel):
    provider: Literal["stripe"] = "stripe"
    publishable_key: str  # public by design; the secret key never leaves the server


class DemoPaymentOut(BaseModel):
    provider: Literal["demo"] = "demo"


class BookingPolicyOut(BaseModel):
    booking_window_days: int
    slot_hold_minutes: int
    payment_hold_minutes: int
    deposit_amount_pence: int
    payment: StripePaymentOut | DemoPaymentOut


@router.get("/booking-policy")
def booking_policy(request: Request, session: SessionDep) -> BookingPolicyOut:
    """How far ahead the page may offer days, how long holds last, and how to take payment."""
    config: AppConfig = request.app.state.config
    payment: StripePaymentOut | DemoPaymentOut = (
        StripePaymentOut(publishable_key=config.stripe_publishable_key)
        if config.payment_provider == "stripe"
        else DemoPaymentOut()
    )
    try:
        return BookingPolicyOut(
            booking_window_days=load_booking_window_days(session),
            slot_hold_minutes=load_hold_minutes(session),
            payment_hold_minutes=load_payment_hold_minutes(session),
            deposit_amount_pence=load_deposit_pence(session),
            payment=payment,
        )
    except SettingsUnavailable as error:
        raise HTTPException(status_code=503, detail="Booking unavailable") from error


@router.get("/garage")
def garage(session: SessionDep) -> GarageOut:
    contact = get_setting(session, "garage_contact")
    timezone = get_setting(session, "garage_timezone")
    unavailable = HTTPException(status_code=503, detail="Garage details unavailable")
    if not isinstance(contact, dict):
        raise unavailable
    try:
        return GarageOut.model_validate({**contact, "timezone": timezone})
    except ValidationError as error:
        raise unavailable from error
