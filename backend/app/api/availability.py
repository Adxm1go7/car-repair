"""Public, read-only availability: which start times are free for some services on one day."""

from datetime import date, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.clock import utc_now
from app.db import get_session
from app.repositories.availability import (
    SettingsUnavailable,
    day_availability,
    find_active_services,
    load_booking_window_days,
    load_policy,
)

router = APIRouter()

SessionDep = Annotated[Session, Depends(get_session)]
NowDep = Annotated[datetime, Depends(utc_now)]


class SlotOut(BaseModel):
    # Strings, not datetimes, so a GMT offset stays "+00:00" instead of becoming "Z".
    start: str
    end: str


class AvailabilityOut(BaseModel):
    date: str
    timezone: str
    duration_minutes: int
    unavailable_reason: Literal["mixed_bay_types"] | None
    slots: list[SlotOut]


def _reject(detail: str) -> HTTPException:
    return HTTPException(status_code=422, detail=detail)


@router.get("/availability")
def availability(
    session: SessionDep,
    now: NowDep,
    services: Annotated[list[str], Query()],
    day: Annotated[date, Query(alias="date")],
) -> AvailabilityOut:
    """Start times in garage local time. `services` may repeat to book several together."""
    try:
        policy = load_policy(session)
        window_days = load_booking_window_days(session)
    except SettingsUnavailable as error:
        raise HTTPException(status_code=503, detail="Availability unavailable") from error

    if not services or any(not slug for slug in services):
        raise _reject("Choose at least one service")
    if len(set(services)) != len(services):
        raise _reject("Each service can only be chosen once")
    found = find_active_services(session, services)
    if len(found) != len(services):
        missing = sorted(set(services) - {service.slug for service in found})
        raise _reject(f"Unknown service: {', '.join(missing)}")

    today = now.astimezone(policy.zone).date()
    if day < today:
        raise _reject("That date has already passed")
    if day > today + timedelta(days=window_days):
        raise _reject(f"Bookings open at most {window_days} days ahead")

    result = day_availability(session, found, day, now, policy)
    return AvailabilityOut(
        date=day.isoformat(),
        timezone=policy.zone.key,
        duration_minutes=result.duration_minutes,
        unavailable_reason=result.unavailable_reason,
        slots=[SlotOut(start=s.start.isoformat(), end=s.end.isoformat()) for s in result.slots],
    )
