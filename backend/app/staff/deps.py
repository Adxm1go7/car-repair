"""What every staff route depends on: a session, the role, and a trusted Origin.

Routers apply these at router level, so a new route can't forget them. The guard tests
walk every route under /api/staff to make sure.
"""

from datetime import datetime
from typing import Annotated, Final

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.clock import utc_now
from app.config import AppConfig
from app.db import get_session
from app.models import StaffUser
from app.staff.sessions import IDLE_LIMIT, find_session_user

COOKIE_NAME: Final = "staff_session"
COOKIE_PATH: Final = "/api/staff"
# The only staff routes anyone may call without a session.
PUBLIC_STAFF_PATHS: Final = frozenset(
    {"/api/staff/login", "/api/staff/forgot-password", "/api/staff/set-password"}
)
# Every admin-only route lives under one of these, behind require_admin at router level.
ADMIN_STAFF_PREFIXES: Final = ("/api/staff/team", "/api/staff/audit")
_WRITE_METHODS: Final = frozenset({"POST", "PUT", "PATCH", "DELETE"})

SessionDep = Annotated[Session, Depends(get_session)]
NowDep = Annotated[datetime, Depends(utc_now)]


def check_origin(request: Request) -> None:
    """Refuse a write that didn't come from our own pages. With the SameSite=Strict cookie,
    this stops another site making a logged-in browser change things."""
    if request.method not in _WRITE_METHODS:
        return
    config: AppConfig = request.app.state.config
    if request.headers.get("origin") not in config.allowed_origins:
        raise HTTPException(status_code=403, detail="Request refused")


def current_staff(request: Request, session: SessionDep, now: NowDep) -> StaffUser:
    token = request.cookies.get(COOKIE_NAME)
    user = find_session_user(session, token, now) if token else None
    if user is None:
        raise HTTPException(status_code=401, detail="Please log in")
    session.commit()  # keep the session's new last_used_at, if it moved
    return user


StaffDep = Annotated[StaffUser, Depends(current_staff)]


def require_admin(user: StaffDep) -> StaffUser:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admins only")
    return user


AdminDep = Annotated[StaffUser, Depends(require_admin)]


def client_ip(request: Request) -> str:
    return request.client.host if request.client is not None else "unknown"


def set_session_cookie(response: Response, token: str, config: AppConfig) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=int(IDLE_LIMIT.total_seconds()),
        path=COOKIE_PATH,
        secure=config.public_base_url.startswith("https://"),
        httponly=True,
        samesite="strict",
    )


def clear_session_cookie(response: Response, config: AppConfig) -> None:
    response.delete_cookie(
        COOKIE_NAME,
        path=COOKIE_PATH,
        secure=config.public_base_url.startswith("https://"),
        httponly=True,
        samesite="strict",
    )
