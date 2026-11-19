"""The staff schedule and the free times staff can book or move into."""

from datetime import date, time
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.api.holds import local_iso
from app.api.validation import resolve_services
from app.repositories.availability import SettingsUnavailable, load_policy
from app.schedule.availability import infos_for_services, staff_free_times
from app.schedule.view import ScheduleItem, load_schedule
from app.staff.deps import NowDep, SessionDep, check_origin, current_staff

router = APIRouter(prefix="/staff", dependencies=[Depends(check_origin), Depends(current_staff)])


class BayOut(BaseModel):
    id: int
    slug: str
    name: str
    bay_type: str
    active: bool  # false: out of use, shown only on days it has bookings or blocks


class BreakOut(BaseModel):
    start: str
    end: str


class DayOut(BaseModel):
    date: str
    open: str | None
    close: str | None
    breaks: list[BreakOut]


class ScheduleItemOut(BaseModel):
    kind: Literal["booking", "block"]
    bay_id: int
    start: str  # garage-local ISO with its offset
    end: str  # a booking's real end, without the bay buffer
    reference: str | None = None
    status: str | None = None
    registration: str | None = None
    services: list[str] | None = None
    source: str | None = None
    has_email: bool | None = None
    block_id: int | None = None
    note: str | None = None


class ScheduleOut(BaseModel):
    timezone: str
    bays: list[BayOut]
    days: list[DayOut]
    items: list[ScheduleItemOut]


class StaffSlotOut(BaseModel):
    start: str
    end: str
    bay_ids: list[int]  # the bays that can take this start; staff choose one


class StaffAvailabilityOut(BaseModel):
    date: str
    timezone: str
    duration_minutes: int
    unavailable_reason: Literal["mixed_bay_types"] | None
    slots: list[StaffSlotOut]


def _hhmm(value: time | None) -> str | None:
    return value.strftime("%H:%M") if value is not None else None


def _item_out(item: ScheduleItem, zone: ZoneInfo) -> ScheduleItemOut:
    common = {
        "bay_id": item.bay_id,
        "start": local_iso(item.start, zone),
        "end": local_iso(item.end, zone),
    }
    if item.booking is not None:
        b = item.booking
        return ScheduleItemOut(
            kind="booking",
            reference=b.reference,
            status=b.status,
            registration=b.car_registration,
            services=[i.service_name for i in b.items],
            source=b.source,
            has_email=b.customer_email is not None,
            **common,
        )
    assert item.block is not None  # noqa: S101 - every item is one or the other
    return ScheduleItemOut(kind="block", block_id=item.block.id, note=item.block.note, **common)


@router.get("/schedule")
def schedule(
    session: SessionDep,
    now: NowDep,
    first: Annotated[date, Query(alias="from")],
    days: Annotated[int, Query(ge=1, le=7)] = 1,
) -> ScheduleOut:
    try:
        zone = load_policy(session).zone
    except SettingsUnavailable as error:
        raise HTTPException(status_code=503, detail="Schedule unavailable") from error
    loaded = load_schedule(session, first, days, zone, now)
    return ScheduleOut(
        timezone=zone.key,
        bays=[
            BayOut(id=b.id, slug=b.slug, name=b.name, bay_type=b.bay_type.name, active=b.active)
            for b in loaded.bays
        ],
        days=[
            DayOut(
                date=d.day.isoformat(),
                open=_hhmm(d.open),
                close=_hhmm(d.close),
                breaks=[
                    BreakOut(start=s.strftime("%H:%M"), end=e.strftime("%H:%M"))
                    for s, e in d.breaks
                ],
            )
            for d in loaded.days
        ],
        items=[_item_out(item, zone) for item in loaded.items],
    )


@router.get("/availability")
def availability(
    session: SessionDep,
    now: NowDep,
    services: Annotated[list[str], Query()],
    day: Annotated[date, Query(alias="date")],
) -> StaffAvailabilityOut:
    """Free starts for these services on `day`, with the bays that can take each. Unlike the
    public endpoint: needs-approval services are allowed (staff approve by booking), and
    there's no cut-off or booking window."""
    try:
        zone = load_policy(session).zone
    except SettingsUnavailable as error:
        raise HTTPException(status_code=503, detail="Availability unavailable") from error
    found = resolve_services(session, services)
    result = staff_free_times(session, infos_for_services(found), day, now)
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
