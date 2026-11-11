"""Read queries for the catalogue. Routes call these; they hold no SQL themselves."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import OpeningHours, Service, Setting


def list_active_services(session: Session) -> list[Service]:
    statement = (
        select(Service).where(Service.active.is_(True)).order_by(Service.sort_order, Service.id)
    )
    return list(session.scalars(statement))


def list_opening_hours(session: Session) -> list[OpeningHours]:
    """The rows that exist, with breaks loaded. A missing weekday is simply absent."""
    statement = (
        select(OpeningHours)
        .options(selectinload(OpeningHours.breaks))
        .order_by(OpeningHours.weekday)
    )
    return list(session.scalars(statement))


def get_setting(session: Session, key: str) -> Any | None:
    setting = session.get(Setting, key)
    return setting.value if setting is not None else None
