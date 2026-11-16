"""Staff login, logout and "who am I". Every failed login gets the same reply."""

from typing import Annotated, Final

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, StringConstraints
from sqlalchemy import select

from app.config import AppConfig
from app.models import StaffUser
from app.staff.deps import (
    COOKIE_NAME,
    NowDep,
    SessionDep,
    StaffDep,
    check_origin,
    clear_session_cookie,
    client_ip,
    current_staff,
    set_session_cookie,
)
from app.staff.passwords import hash_password, password_matches
from app.staff.sessions import create_session, end_session
from app.staff.throttle import is_locked, normalise_email, record_attempt

# Anyone may call these; check_origin still applies.
public_router = APIRouter(prefix="/staff", dependencies=[Depends(check_origin)])
# Everything else: a valid session first.
router = APIRouter(prefix="/staff", dependencies=[Depends(check_origin), Depends(current_staff)])

WRONG: Final = HTTPException(status_code=401, detail="Email or password is wrong")
# Checked against when the email is unknown, so a login takes as long either way and its
# timing doesn't tell anyone which emails have accounts.
_DUMMY_HASH: Final = hash_password("not anyone's password")


class LoginIn(BaseModel):
    email: Annotated[str, StringConstraints(max_length=254)]
    password: Annotated[str, StringConstraints(max_length=200)]


class StaffMeOut(BaseModel):
    id: int
    name: str
    email: str
    role: str


def me_out(user: StaffUser) -> StaffMeOut:
    return StaffMeOut(id=user.id, name=user.name, email=user.email, role=user.role)


@public_router.post("/login")
def login(
    body: LoginIn, request: Request, response: Response, session: SessionDep, now: NowDep
) -> StaffMeOut:
    email = normalise_email(body.email)
    ip = client_ip(request)
    if is_locked(session, email, ip, now):
        record_attempt(session, email, ip, False, now)
        session.commit()
        raise WRONG
    user = session.scalars(select(StaffUser).where(StaffUser.email == email)).one_or_none()
    matches = password_matches(body.password, user.password_hash if user else _DUMMY_HASH)
    ok = user is not None and user.active and matches
    record_attempt(session, email, ip, ok, now)
    if not ok or user is None:
        session.commit()
        raise WRONG
    token = create_session(session, user, now)
    session.commit()
    set_session_cookie(response, token, request.app.state.config)
    return me_out(user)


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, session: SessionDep) -> None:
    config: AppConfig = request.app.state.config
    end_session(session, request.cookies.get(COOKIE_NAME, ""))
    session.commit()
    clear_session_cookie(response, config)


@router.get("/me")
def me(user: StaffDep) -> StaffMeOut:
    return me_out(user)
