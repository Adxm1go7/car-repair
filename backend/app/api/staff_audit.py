"""Admin only: the audit log of every staff change."""

from datetime import date, timedelta
from typing import Annotated, Any, Final

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.holds import local_iso
from app.models import AuditEntry
from app.repositories.availability import load_policy
from app.schedule.view import local_midnight
from app.staff.deps import SessionDep, check_origin, require_admin

router = APIRouter(
    prefix="/staff/audit", dependencies=[Depends(check_origin), Depends(require_admin)]
)

PAGE_SIZE: Final = 50


class AuditEntryOut(BaseModel):
    at: str
    staff_name: str  # "Setup" for the create_admin command
    action: str
    entity_type: str
    entity_id: int
    booking_reference: str | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    reason: str | None


class AuditPageOut(BaseModel):
    entries: list[AuditEntryOut]
    page: int
    has_more: bool


@router.get("")
def audit_log(
    session: SessionDep,
    first: Annotated[date | None, Query(alias="from")] = None,
    last: Annotated[date | None, Query(alias="to")] = None,
    staff: Annotated[int | None, Query()] = None,
    reference: Annotated[str | None, Query(max_length=9)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
) -> AuditPageOut:
    """Newest first. `from` and `to` are garage-local dates, both included."""
    zone = load_policy(session).zone
    statement = select(AuditEntry).options(selectinload(AuditEntry.staff_user))
    if first is not None:
        statement = statement.where(AuditEntry.at >= local_midnight(first, zone))
    if last is not None:
        statement = statement.where(AuditEntry.at < local_midnight(last + timedelta(days=1), zone))
    if staff is not None:
        statement = statement.where(AuditEntry.staff_user_id == staff)
    if reference:
        statement = statement.where(AuditEntry.booking_reference == reference.strip().upper())
    # One more than a page, to know whether there's another.
    rows = list(
        session.scalars(
            statement.order_by(AuditEntry.at.desc(), AuditEntry.id.desc())
            .offset((page - 1) * PAGE_SIZE)
            .limit(PAGE_SIZE + 1)
        )
    )
    return AuditPageOut(
        entries=[
            AuditEntryOut(
                at=local_iso(e.at, zone),
                staff_name=e.staff_user.name if e.staff_user is not None else "Setup",
                action=e.action,
                entity_type=e.entity_type,
                entity_id=e.entity_id,
                booking_reference=e.booking_reference,
                before=e.before,
                after=e.after,
                reason=e.reason,
            )
            for e in rows[:PAGE_SIZE]
        ],
        page=page,
        has_more=len(rows) > PAGE_SIZE,
    )
