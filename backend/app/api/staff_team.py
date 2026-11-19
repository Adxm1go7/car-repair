"""Admin only: the garage's staff accounts."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import AfterValidator, BaseModel
from sqlalchemy import select

from app.api.validation import ResourceId
from app.bookings.rules import clean_email, clean_name
from app.models import StaffUser
from app.staff.accounts import (
    EmailTaken,
    LastAdmin,
    StaffState,
    admin_reset_password,
    invite_staff,
    staff_state,
    update_staff,
)
from app.staff.deps import AdminDep, NowDep, SessionDep, check_origin, require_admin

router = APIRouter(
    prefix="/staff/team", dependencies=[Depends(check_origin), Depends(require_admin)]
)

Role = Literal["admin", "staff"]
NOT_FOUND = HTTPException(status_code=404, detail="No such account")


class InviteIn(BaseModel):
    name: Annotated[str, AfterValidator(clean_name)]
    email: Annotated[str, AfterValidator(clean_email)]
    role: Role


class UpdateIn(BaseModel):
    role: Role | None = None
    active: bool | None = None


class TeamMemberOut(BaseModel):
    id: int
    name: str
    email: str
    role: str
    state: StaffState


def member_out(user: StaffUser) -> TeamMemberOut:
    return TeamMemberOut(
        id=user.id, name=user.name, email=user.email, role=user.role, state=staff_state(user)
    )


def _get(session: SessionDep, user_id: ResourceId) -> StaffUser:
    user = session.get(StaffUser, user_id)
    if user is None:
        raise NOT_FOUND
    return user


@router.get("")
def list_team(session: SessionDep) -> list[TeamMemberOut]:
    users = session.scalars(select(StaffUser).order_by(StaffUser.active.desc(), StaffUser.name))
    return [member_out(user) for user in users]


@router.post("", status_code=201)
def invite(body: InviteIn, admin: AdminDep, session: SessionDep, now: NowDep) -> TeamMemberOut:
    try:
        user = invite_staff(session, admin, body.name, body.email, body.role, now)
    except EmailTaken as error:
        raise HTTPException(status_code=409, detail="That email already has an account") from error
    session.commit()
    return member_out(user)


@router.patch("/{user_id}")
def update(
    user_id: ResourceId, body: UpdateIn, admin: AdminDep, session: SessionDep, now: NowDep
) -> TeamMemberOut:
    user = _get(session, user_id)
    try:
        update_staff(session, admin, user, role=body.role, active=body.active, now=now)
    except LastAdmin as error:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="The garage needs at least one admin"
        ) from error
    session.commit()
    return member_out(user)


@router.post("/{user_id}/reset-password", status_code=202)
def reset_password(
    user_id: ResourceId, admin: AdminDep, session: SessionDep, now: NowDep
) -> TeamMemberOut:
    user = _get(session, user_id)
    admin_reset_password(session, admin, user, now)
    session.commit()
    return member_out(user)
