"""Read queries for the catalogue. Routes call these; they hold no SQL themselves."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Service, Setting


def list_active_services(session: Session) -> list[Service]:
    statement = (
        select(Service).where(Service.active.is_(True)).order_by(Service.sort_order, Service.id)
    )
    return list(session.scalars(statement))


def get_setting(session: Session, key: str) -> Any | None:
    setting = session.get(Setting, key)
    return setting.value if setting is not None else None
