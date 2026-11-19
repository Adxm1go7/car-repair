"""Admin only: the garage's settings — services, bays, opening hours and contact details."""

from typing import Annotated, Any, Final, Self

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.models import Service
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
