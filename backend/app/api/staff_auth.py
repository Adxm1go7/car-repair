"""Staff login, logout, "who am I", forgotten passwords and set-password links.

Every failed login gets the same reply, and so does every forgot-password request.
"""

from typing import Annotated, Final

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import AfterValidator, BaseModel, StringConstraints
from sqlalchemy import select

from app.bookings.rules import reject_control_chars
from app.config import AppConfig
from app.email.queue import queue_staff_email
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
from app.staff.links import use_password_token
from app.staff.passwords import clean_password, hash_password, password_matches
from app.staff.sessions import create_session, end_all_sessions, end_session
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
    email: Annotated[str, StringConstraints(max_length=254), AfterValidator(reject_control_chars)]
    password: Annotated[str, StringConstraints(max_length=200)]


class ForgotIn(BaseModel):
    email: Annotated[str, StringConstraints(max_length=254), AfterValidator(reject_control_chars)]


class SetPasswordIn(BaseModel):
    # A plain str: an oversized token must get the same 400 as any bad link, not a 422.
    token: str
    password: Annotated[str, AfterValidator(clean_password)]


class MessageOut(BaseModel):
    detail: str


LINK_SENT: Final = "If that address has an account, we've emailed a link"
LINK_NOT_VALID: Final = HTTPException(status_code=400, detail="This link isn't valid any more")


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
    # Always run a real hash check, even for an unknown email or an account with no password
    # yet, so the answer takes as long either way and doesn't reveal which emails exist.
    stored = user.password_hash if user is not None else None
    matches = password_matches(body.password, stored or _DUMMY_HASH) and stored is not None
    ok = user is not None and user.active and matches
    record_attempt(session, email, ip, ok, now)
    if not ok or user is None:
        session.commit()
        raise WRONG
    token = create_session(session, user, now)
    session.commit()
    set_session_cookie(response, token, request.app.state.config)
    return me_out(user)


@public_router.post("/forgot-password", status_code=202)
def forgot_password(
    body: ForgotIn, request: Request, session: SessionDep, now: NowDep
) -> MessageOut:
    """Email a reset link if the account exists. The current password keeps working, so
    nobody can lock a colleague out by typing their email. Counts towards the lockout."""
    email = normalise_email(body.email)
    ip = client_ip(request)
    locked = is_locked(session, email, ip, now)
    record_attempt(session, email, ip, False, now)
    if not locked:
        user = session.scalars(select(StaffUser).where(StaffUser.email == email)).one_or_none()
        if user is not None and user.active:
            queue_staff_email(session, "password_reset", user)
    session.commit()
    return MessageOut(detail=LINK_SENT)


@public_router.post("/set-password")
def set_password(
    body: SetPasswordIn, request: Request, response: Response, session: SessionDep, now: NowDep
) -> StaffMeOut:
    """Use an invite or reset link: set the password, end every other session, log in."""
    user = use_password_token(session, body.token, now)
    if user is None:
        raise LINK_NOT_VALID
    user.password_hash = hash_password(body.password)
    end_all_sessions(session, user.id)
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
