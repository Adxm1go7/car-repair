"""What admins do to staff accounts: invite, change role, remove, restore and reset.

The garage always keeps at least one active admin. Each change is audited and queues any
email in the same transaction. Nothing here commits.
"""

from datetime import datetime
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.email.queue import queue_staff_email
from app.models import StaffUser
from app.staff.audit import record_audit
from app.staff.sessions import end_all_sessions

StaffState = Literal["invited", "active", "reset_sent", "removed"]


class LastAdmin(Exception):
    """The change would leave the garage without an active admin."""


class EmailTaken(Exception):
    """Another account already has this email."""


def staff_state(user: StaffUser) -> StaffState:
    if not user.active:
        return "removed"
    if user.password_hash is None:
        return "invited" if user.last_login_at is None else "reset_sent"
    return "active"


def _snapshot(user: StaffUser) -> dict[str, Any]:
    """What the audit log keeps about an account: never a password or token."""
    return {"name": user.name, "email": user.email, "role": user.role, "active": user.active}


def invite_staff(
    session: Session, admin: StaffUser, name: str, email: str, role: str, now: datetime
) -> StaffUser:
    """`name` and `email` already cleaned (email lowercase). Raises EmailTaken."""
    if session.scalars(select(StaffUser.id).where(StaffUser.email == email)).first() is not None:
        raise EmailTaken
    user = StaffUser(name=name, email=email, role=role)
    session.add(user)
    session.flush()
    session.refresh(user)  # load the server defaults (active)
    queue_staff_email(session, "staff_invite", user)
    record_audit(
        session, admin, "staff.invite", "staff_user", user.id, after=_snapshot(user), now=now
    )
    return user


def _lock_active_admins(session: Session) -> list[StaffUser]:
    """Every active admin, locked: two admins removing each other at once take turns, and
    the second sees the first's change."""
    return list(
        session.scalars(
            select(StaffUser)
            .where(StaffUser.role == "admin", StaffUser.active.is_(True))
            .order_by(StaffUser.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )


def update_staff(
    session: Session,
    admin: StaffUser,
    user: StaffUser,
    *,
    role: str | None,
    active: bool | None,
    now: datetime,
) -> None:
    """Change role and/or active. Removing clears the password and ends every session;
    restoring sends a fresh set-password link. Raises LastAdmin."""
    admins = _lock_active_admins(session)
    session.refresh(user)
    stops_being_admin = (
        user.role == "admin"
        and user.active
        and ((role is not None and role != "admin") or active is False)
    )
    if stops_being_admin and [a.id for a in admins] == [user.id]:
        raise LastAdmin

    if role is not None and role != user.role:
        before = _snapshot(user)
        user.role = role
        record_audit(
            session,
            admin,
            "staff.role",
            "staff_user",
            user.id,
            before=before,
            after=_snapshot(user),
            now=now,
        )
    if active is False and user.active:
        before = _snapshot(user)
        user.active = False
        user.password_hash = None
        end_all_sessions(session, user.id)
        record_audit(
            session,
            admin,
            "staff.remove",
            "staff_user",
            user.id,
            before=before,
            after=_snapshot(user),
            now=now,
        )
    elif active is True and not user.active:
        before = _snapshot(user)
        user.active = True
        user.password_hash = None
        queue_staff_email(session, "staff_invite", user)
        record_audit(
            session,
            admin,
            "staff.restore",
            "staff_user",
            user.id,
            before=before,
            after=_snapshot(user),
            now=now,
        )
    session.flush()


def admin_reset_password(
    session: Session, admin: StaffUser, user: StaffUser, now: datetime
) -> None:
    """Lock the account out until its owner uses the emailed link: the old password stops
    working and every session ends. For an account that may be compromised."""
    user.password_hash = None
    end_all_sessions(session, user.id)
    queue_staff_email(session, "password_reset", user)
    record_audit(
        session,
        admin,
        "staff.reset_password",
        "staff_user",
        user.id,
        after=_snapshot(user),
        now=now,
    )
