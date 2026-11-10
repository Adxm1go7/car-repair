"""Public, read-only catalogue endpoints: services, opening hours, garage details."""

from datetime import time
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy.orm import Session

from app.db import get_session
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
