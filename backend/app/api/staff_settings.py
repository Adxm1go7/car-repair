"""Admin only: the garage's settings — services, bays, opening hours and contact details."""

from typing import Annotated, Any, Final, Self

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.models import Bay, BayType, Service
from app.repositories.availability import SettingsUnavailable, load_policy
from app.settings import bays as bay_settings
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
    try:
        zone = load_policy(session).zone
    except SettingsUnavailable as error:
        raise HTTPException(status_code=503, detail="Settings unavailable") from error
    changes = {field: getattr(body, field) for field in body.model_fields_set}
    try:
        bay_settings.update_bay(session, admin, bay, changes, now)
    except bay_settings.NameTaken as error:
        raise NAME_TAKEN from error
    except bay_settings.BayInUse as error:
        body_409 = clash_body(error.bookings, zone)
        session.rollback()
        return JSONResponse(status_code=409, content=body_409)
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
