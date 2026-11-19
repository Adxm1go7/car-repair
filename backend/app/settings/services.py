"""Admins' changes to the service list: add, edit, hide or show, and reorder.

None of these can clash with bookings, because a booking keeps its own copy of each service's
name, price and duration. Each change writes its audit entry in the same transaction.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import BayType, Service, StaffUser
from app.settings.slugs import make_slug
from app.staff.audit import record_audit

ApprovalMode = Literal["instant", "needs_approval"]
Direction = Literal["up", "down"]
# The fields PATCH may change, besides `active`.
EDITABLE: Final = (
    "name",
    "category",
    "description",
    "duration_minutes",
    "price_from_pence",
    "price_to_pence",
)


class NameTaken(Exception):
    """Another service already has this name (ignoring case)."""


class UnknownBayType(Exception):
    pass


class BadPrice(Exception):
    """The "to" price is below the "from" price."""


@dataclass(frozen=True)
class NewService:
    name: str
    category: str
    description: str
    duration_minutes: int
    price_from_pence: int
    price_to_pence: int | None
    bay_type_id: int
    approval_mode: ApprovalMode


def list_services(session: Session) -> list[Service]:
    """Every service, shown and hidden, in display order."""
    return list(session.scalars(select(Service).order_by(Service.sort_order, Service.id)))


def snapshot(service: Service) -> dict[str, Any]:
    return {
        "slug": service.slug,
        **{field: getattr(service, field) for field in EDITABLE},
        "bay_type_id": service.required_bay_type_id,
        "approval_mode": service.approval_mode,
        "active": service.active,
    }


def _lock_services(session: Session) -> list[Service]:
    """Lock every service row, so two admins adding or moving at once can't give two services
    the same place in the list."""
    statement = select(Service).order_by(Service.sort_order, Service.id).with_for_update()
    return list(session.scalars(statement))


def _check_name_free(session: Session, name: str, service_id: int | None = None) -> None:
    statement = select(Service.id).where(func.lower(Service.name) == name.lower())
    if service_id is not None:
        statement = statement.where(Service.id != service_id)
    if session.scalars(statement).first() is not None:
        raise NameTaken


def _check_prices(price_from: int, price_to: int | None) -> None:
    if price_to is not None and price_to < price_from:
        raise BadPrice


def create_service(session: Session, admin: StaffUser, new: NewService, now: datetime) -> Service:
    """Add a service at the end of the list, shown."""
    if session.get(BayType, new.bay_type_id) is None:
        raise UnknownBayType
    _check_prices(new.price_from_pence, new.price_to_pence)
    services = _lock_services(session)
    _check_name_free(session, new.name)
    service = Service(
        slug=make_slug(new.name, {service.slug for service in services}),
        name=new.name,
        category=new.category,
        description=new.description,
        duration_minutes=new.duration_minutes,
        price_from_pence=new.price_from_pence,
        price_to_pence=new.price_to_pence,
        required_bay_type_id=new.bay_type_id,
        approval_mode=new.approval_mode,
        active=True,
        sort_order=max((service.sort_order for service in services), default=0) + 1,
    )
    session.add(service)
    session.flush()
    record_audit(
        session, admin, "service.create", "service", service.id, after=snapshot(service), now=now
    )
    return service


def update_service(
    session: Session, admin: StaffUser, service: Service, changes: Mapping[str, Any], now: datetime
) -> None:
    """Apply the fields given (and only those). Changed fields get one `service.update` entry,
    and a change to `active` its own `service.hide` or `service.show`. No change, no entry."""
    edits = {
        field: value
        for field, value in changes.items()
        if field in EDITABLE and getattr(service, field) != value
    }
    if "name" in edits:
        _check_name_free(session, edits["name"], service.id)
    _check_prices(
        edits.get("price_from_pence", service.price_from_pence),
        edits.get("price_to_pence", service.price_to_pence),
    )
    if edits:
        # Each entry names the service (as it was, and as it is now), so the log can say which.
        before = {"name": service.name, **{field: getattr(service, field) for field in edits}}
        for field, value in edits.items():
            setattr(service, field, value)
        session.flush()
        record_audit(
            session,
            admin,
            "service.update",
            "service",
            service.id,
            before=before,
            after={"name": service.name, **edits},
            now=now,
        )
    active = changes.get("active")
    if active is not None and active != service.active:
        service.active = active
        session.flush()
        record_audit(
            session,
            admin,
            "service.show" if active else "service.hide",
            "service",
            service.id,
            before={"name": service.name, "active": not active},
            after={"name": service.name, "active": active},
            now=now,
        )


def move_service(
    session: Session, admin: StaffUser, service: Service, direction: Direction, now: datetime
) -> None:
    """Swap the service with its neighbour. At either end nothing changes and nothing is
    written. The list is numbered 1, 2, 3… afterwards, so ties left by older data can't stop
    a move."""
    services = _lock_services(session)
    index = services.index(service)
    other = index - 1 if direction == "up" else index + 1
    if not 0 <= other < len(services):
        return
    services[index], services[other] = services[other], services[index]
    for position, each in enumerate(services, start=1):
        each.sort_order = position
    session.flush()
    record_audit(
        session,
        admin,
        "service.move",
        "service",
        service.id,
        before={"name": service.name, "position": index + 1},
        after={"name": service.name, "position": other + 1},
        now=now,
    )
