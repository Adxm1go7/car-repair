"""Admin only: the garage's settings — services, bays, opening hours and contact details."""

from collections.abc import Sequence
from datetime import date, datetime, time
from typing import Annotated, Any, Final, Self
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import JSONResponse
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)
from sqlalchemy.orm import Session

from app.api.catalogue import OpeningDayOut, week_out
from app.models import Bay, BayType, Booking, Service
from app.repositories.availability import SettingsUnavailable, load_policy
from app.repositories.hours import WeekdayHours
from app.settings import bays as bay_settings
from app.settings import hours as hours_settings
from app.settings.clashes import clash_body
from app.settings.services import (
    EDITABLE,
    ApprovalMode,
    BadPrice,
    Direction,
    NameTaken,
    NewService,
    UnknownBayType,
    create_service,
    list_services,
    move_service,
    update_service,
)
from app.staff.deps import AdminDep, NowDep, SessionDep, check_origin, require_admin

router = APIRouter(
    prefix="/staff/settings", dependencies=[Depends(check_origin), Depends(require_admin)]
)

MAX_PRICE_PENCE: Final = 9_999_999  # £99,999.99, well inside the integer columns

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Category = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
Description = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Minutes = Annotated[int, Field(ge=15, le=480, multiple_of=15)]
Pence = Annotated[int, Field(ge=0, le=MAX_PRICE_PENCE)]

SERVICE_NOT_FOUND = HTTPException(status_code=404, detail="No such service")
NAME_TAKEN = HTTPException(status_code=409, detail="That name is already used")
BAD_PRICE = HTTPException(status_code=422, detail="The top price can't be below the lowest")


class ServiceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    category: Category
    description: Description
    duration_minutes: Minutes
    price_from_pence: Pence
    price_to_pence: Pence | None = None
    bay_type_id: int
    approval_mode: ApprovalMode


class ServicePatch(BaseModel):
    """Only the fields sent are changed. `price_to_pence: null` clears the top price; any
    other field sent as null is refused. Bay type and approval mode can't be changed."""

    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    category: Category | None = None
    description: Description | None = None
    duration_minutes: Minutes | None = None
    price_from_pence: Pence | None = None
    price_to_pence: Pence | None = None
    active: bool | None = None

    @model_validator(mode="after")
    def only_price_to_may_be_null(self) -> Self:
        for field in self.model_fields_set - {"price_to_pence"}:
            if getattr(self, field) is None:
                raise ValueError(f"{field} can't be empty")
        return self

    def changes(self) -> dict[str, Any]:
        return {field: getattr(self, field) for field in self.model_fields_set}


class MoveIn(BaseModel):
    direction: Direction


class ServiceAdminOut(BaseModel):
    id: int
    slug: str
    name: str
    category: str
    description: str
    duration_minutes: int
    price_from_pence: int
    price_to_pence: int | None
    bay_type_id: int
    bay_type: str
    approval_mode: str
    active: bool
    sort_order: int


def service_out(service: Service) -> ServiceAdminOut:
    return ServiceAdminOut(
        id=service.id,
        slug=service.slug,
        **{field: getattr(service, field) for field in EDITABLE},
        bay_type_id=service.required_bay_type_id,
        bay_type=service.required_bay_type.name,
        approval_mode=service.approval_mode,
        active=service.active,
        sort_order=service.sort_order,
    )


def _zone(session: Session) -> ZoneInfo:
    try:
        return load_policy(session).zone
    except SettingsUnavailable as error:
        raise HTTPException(status_code=503, detail="Settings unavailable") from error


def _clash_response(session: Session, bookings: Sequence[Booking], zone: ZoneInfo) -> JSONResponse:
    """The 409 listing what's in the way. Built before the rollback, which expires them."""
    body = clash_body(bookings, zone)
    session.rollback()
    return JSONResponse(status_code=409, content=body)


def _get_service(session: SessionDep, service_id: int) -> Service:
    service = session.get(Service, service_id)
    if service is None:
        raise SERVICE_NOT_FOUND
    return service


@router.get("/services")
def get_services(session: SessionDep) -> list[ServiceAdminOut]:
    return [service_out(service) for service in list_services(session)]


@router.post("/services", status_code=201)
def add_service(
    body: ServiceIn, admin: AdminDep, session: SessionDep, now: NowDep
) -> ServiceAdminOut:
    try:
        service = create_service(session, admin, NewService(**body.model_dump()), now)
    except NameTaken as error:
        raise NAME_TAKEN from error
    except UnknownBayType as error:
        raise HTTPException(status_code=422, detail="Unknown bay type") from error
    except BadPrice as error:
        raise BAD_PRICE from error
    session.commit()
    return service_out(service)


@router.patch("/services/{service_id}")
def edit_service(
    service_id: int, body: ServicePatch, admin: AdminDep, session: SessionDep, now: NowDep
) -> ServiceAdminOut:
    service = _get_service(session, service_id)
    try:
        update_service(session, admin, service, body.changes(), now)
    except NameTaken as error:
        raise NAME_TAKEN from error
    except BadPrice as error:
        raise BAD_PRICE from error
    session.commit()
    return service_out(service)


@router.post("/services/{service_id}/move")
def move(
    service_id: int, body: MoveIn, admin: AdminDep, session: SessionDep, now: NowDep
) -> list[ServiceAdminOut]:
    service = _get_service(session, service_id)
    move_service(session, admin, service, body.direction, now)
    session.commit()
    return [service_out(each) for each in list_services(session)]


# Bays and bay types


class BayIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    bay_type_id: int


class BayPatch(BaseModel):
    """Only the fields sent are changed; neither may be null. The bay type can't change."""

    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    active: bool | None = None

    @model_validator(mode="after")
    def nothing_null(self) -> Self:
        for field in self.model_fields_set:
            if getattr(self, field) is None:
                raise ValueError(f"{field} can't be empty")
        return self


class BayTypeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name


class BayAdminOut(BaseModel):
    id: int
    slug: str
    name: str
    bay_type_id: int
    bay_type: str
    active: bool


class BayTypeOut(BaseModel):
    id: int
    slug: str
    name: str


def bay_out(bay: Bay) -> BayAdminOut:
    return BayAdminOut(
        id=bay.id,
        slug=bay.slug,
        name=bay.name,
        bay_type_id=bay.bay_type_id,
        bay_type=bay.bay_type.name,
        active=bay.active,
    )


def bay_type_out(bay_type: BayType) -> BayTypeOut:
    return BayTypeOut(id=bay_type.id, slug=bay_type.slug, name=bay_type.name)


@router.get("/bays")
def get_bays(session: SessionDep) -> list[BayAdminOut]:
    return [bay_out(bay) for bay in bay_settings.list_bays(session)]


@router.post("/bays", status_code=201)
def add_bay(body: BayIn, admin: AdminDep, session: SessionDep, now: NowDep) -> BayAdminOut:
    try:
        bay = bay_settings.create_bay(session, admin, body.name, body.bay_type_id, now)
    except bay_settings.NameTaken as error:
        raise NAME_TAKEN from error
    except bay_settings.UnknownBayType as error:
        raise HTTPException(status_code=422, detail="Unknown bay type") from error
    session.commit()
    return bay_out(bay)


@router.patch("/bays/{bay_id}", response_model=BayAdminOut)
def edit_bay(
    bay_id: int, body: BayPatch, admin: AdminDep, session: SessionDep, now: NowDep
) -> BayAdminOut | JSONResponse:
    bay = session.get(Bay, bay_id)
    if bay is None:
        raise HTTPException(status_code=404, detail="No such bay")
    zone = _zone(session)
    changes = {field: getattr(body, field) for field in body.model_fields_set}
    try:
        bay_settings.update_bay(session, admin, bay, changes, now)
    except bay_settings.NameTaken as error:
        raise NAME_TAKEN from error
    except bay_settings.BayInUse as error:
        return _clash_response(session, error.bookings, zone)
    session.commit()
    return bay_out(bay)


@router.get("/bay-types")
def get_bay_types(session: SessionDep) -> list[BayTypeOut]:
    return [bay_type_out(bay_type) for bay_type in bay_settings.list_bay_types(session)]


@router.post("/bay-types", status_code=201)
def add_bay_type(body: BayTypeIn, admin: AdminDep, session: SessionDep, now: NowDep) -> BayTypeOut:
    try:
        bay_type = bay_settings.create_bay_type(session, admin, body.name, now)
    except bay_settings.NameTaken as error:
        raise NAME_TAKEN from error
    session.commit()
    return bay_type_out(bay_type)


# Opening hours: timetables


class BreakIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: time
    end: time


class DayIn(BaseModel):
    """A weekday's hours: open and close both set, or both null for a closed day. Breaks lie
    inside the hours, start before they end, and don't overlap (touching is fine)."""

    model_config = ConfigDict(extra="forbid")

    weekday: Annotated[int, Field(ge=0, le=6)]
    open: time | None
    close: time | None
    breaks: Annotated[list[BreakIn], Field(max_length=10)] = []

    @model_validator(mode="after")
    def hours_make_sense(self) -> Self:
        if (self.open is None) != (self.close is None):
            raise ValueError("Give both opening and closing times, or neither")
        if self.open is None or self.close is None:
            if self.breaks:
                raise ValueError("A closed day can't have breaks")
            return self
        if self.open >= self.close:
            raise ValueError("Opening must be before closing")
        previous_end = self.open
        for each in sorted(self.breaks, key=lambda b: b.start):
            if each.start >= each.end:
                raise ValueError("A break must start before it ends")
            if each.start < previous_end or each.end > self.close:
                raise ValueError("Breaks must be inside the hours and not overlap")
            previous_end = each.end
        return self

    def hours(self) -> WeekdayHours:
        breaks = tuple(sorted((b.start, b.end) for b in self.breaks))
        return WeekdayHours(self.open, self.close, breaks)


def _seven_days(days: list[DayIn]) -> list[DayIn]:
    if sorted(day.weekday for day in days) != list(range(7)):
        raise ValueError("Give each weekday, Monday to Sunday, once")
    return days


SevenDays = Annotated[list[DayIn], AfterValidator(_seven_days)]


def _week(days: list[DayIn]) -> dict[int, WeekdayHours]:
    return {day.weekday: day.hours() for day in days}


class TimetableIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    starts_on: date
    days: SevenDays


class TimetableDaysIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    days: SevenDays


class TimetableAdminOut(BaseModel):
    id: int
    starts_on: str
    state: hours_settings.State
    days: list[OpeningDayOut]


def _not_allowed(session: Session) -> JSONResponse:
    session.rollback()
    return JSONResponse(status_code=409, content={"detail": "not_allowed"})


def _timetables_out(session: Session, zone: ZoneInfo, now: datetime) -> list[TimetableAdminOut]:
    timetables = hours_settings.list_timetables(session)
    states = hours_settings.states(timetables, now.astimezone(zone).date())
    return [
        TimetableAdminOut(
            id=t.id, starts_on=t.starts_on.isoformat(), state=states[t.id], days=week_out(t)
        )
        for t in timetables
    ]


def _timetable_out(
    session: Session, zone: ZoneInfo, now: datetime, timetable_id: int
) -> TimetableAdminOut:
    return next(t for t in _timetables_out(session, zone, now) if t.id == timetable_id)


@router.get("/hours")
def get_hours(session: SessionDep, now: NowDep) -> list[TimetableAdminOut]:
    """Every timetable, oldest first, marked past, current (in force today) or future."""
    return _timetables_out(session, _zone(session), now)


@router.post("/hours", status_code=201, response_model=TimetableAdminOut)
def add_hours(
    body: TimetableIn, admin: AdminDep, session: SessionDep, now: NowDep
) -> TimetableAdminOut | JSONResponse:
    zone = _zone(session)
    try:
        timetable = hours_settings.create_timetable(
            session, admin, body.starts_on, _week(body.days), zone, now
        )
    except hours_settings.StartTooSoon as error:
        raise HTTPException(
            status_code=422, detail="New hours can start tomorrow at the earliest"
        ) from error
    except hours_settings.DateTaken as error:
        raise HTTPException(
            status_code=422, detail="There are already hours from that date"
        ) from error
    except hours_settings.HoursClash as error:
        return _clash_response(session, error.bookings, zone)
    session.commit()
    return _timetable_out(session, zone, now, timetable.id)


@router.put("/hours/{timetable_id}", response_model=TimetableAdminOut)
def replace_hours(
    timetable_id: int, body: TimetableDaysIn, admin: AdminDep, session: SessionDep, now: NowDep
) -> TimetableAdminOut | JSONResponse:
    zone = _zone(session)
    try:
        hours_settings.replace_timetable(session, admin, timetable_id, _week(body.days), zone, now)
    except LookupError as error:
        raise HTTPException(status_code=404, detail="No such hours") from error
    except hours_settings.NotAllowed:
        return _not_allowed(session)
    except hours_settings.HoursClash as error:
        return _clash_response(session, error.bookings, zone)
    session.commit()
    return _timetable_out(session, zone, now, timetable_id)


@router.delete("/hours/{timetable_id}", status_code=204, response_model=None)
def delete_hours(timetable_id: int, admin: AdminDep, session: SessionDep, now: NowDep) -> Response:
    zone = _zone(session)
    try:
        hours_settings.delete_timetable(session, admin, timetable_id, zone, now)
    except LookupError as error:
        raise HTTPException(status_code=404, detail="No such hours") from error
    except hours_settings.NotAllowed:
        return _not_allowed(session)
    except hours_settings.HoursClash as error:
        return _clash_response(session, error.bookings, zone)
    session.commit()
    return Response(status_code=204)
