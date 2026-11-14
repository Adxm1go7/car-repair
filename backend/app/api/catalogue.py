"""Public, read-only catalogue endpoints: services, opening hours, garage details."""

from datetime import time
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy.orm import Session

from app.config import AppConfig
from app.db import get_session
from app.repositories.availability import (
    SettingsUnavailable,
    load_booking_window_days,
    load_deposit_pence,
    load_hold_minutes,
    load_payment_hold_minutes,
)
from app.repositories.catalogue import get_setting, list_active_services, list_opening_hours

router = APIRouter()

SessionDep = Annotated[Session, Depends(get_session)]


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


@router.get("/services")
def services(session: SessionDep) -> list[ServiceOut]:
    return [ServiceOut.model_validate(service) for service in list_active_services(session)]


@router.get("/opening-hours")
def opening_hours(session: SessionDep) -> list[OpeningDayOut]:
    """Always Monday to Sunday; a weekday with no row is reported as closed."""
    rows = {row.weekday: row for row in list_opening_hours(session)}
    days = []
    for weekday in range(7):
        row = rows.get(weekday)
        if row is None or row.open_time is None or row.close_time is None:
            days.append(OpeningDayOut(weekday=weekday, open=None, close=None, breaks=[]))
            continue
        days.append(
            OpeningDayOut(
                weekday=weekday,
                open=_hhmm(row.open_time),
                close=_hhmm(row.close_time),
                breaks=[
                    BreakOut(start=_hhmm(b.start_time), end=_hhmm(b.end_time)) for b in row.breaks
                ],
            )
        )
    return days


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
