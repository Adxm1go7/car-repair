"""Staff login sessions. The browser holds a random token; the database holds its hash.

A session ends after 7 days unused, or 30 days after it began however much it's used.
Removing a user or resetting their password ends every session they have.
Nothing here commits.
"""

from datetime import datetime, timedelta
from typing import Final

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from app.bookings.rules import hash_token, new_hold_token
from app.models import StaffSession, StaffUser

IDLE_LIMIT: Final = timedelta(days=7)
SESSION_CAP: Final = timedelta(days=30)
# Writing last_used_at on every request would turn each read into a write.
TOUCH_EVERY: Final = timedelta(minutes=1)
# A real token is 43 characters. Anything much longer isn't one, so don't hash it.
MAX_TOKEN_LENGTH: Final = 100


def create_session(session: Session, user: StaffUser, now: datetime) -> str:
    """Start a session for `user` and return its plain token, the only copy there is."""
    token = new_hold_token()
    session.add(
        StaffSession(
            staff_user_id=user.id,
            token_hash=hash_token(token),
            created_at=now,
            last_used_at=now,
            expires_at=now + SESSION_CAP,
        )
    )
    user.last_login_at = now
    session.flush()
    return token


def find_session_user(session: Session, token: str, now: datetime) -> StaffUser | None:
    """The active user this token belongs to, or None. Using it keeps the session alive."""
    if len(token) > MAX_TOKEN_LENGTH:
        return None
    row = session.scalars(
        select(StaffSession).where(StaffSession.token_hash == hash_token(token))
    ).one_or_none()
    if row is None or now >= row.expires_at or now >= row.last_used_at + IDLE_LIMIT:
        return None
    user = row.staff_user
    if not user.active:
        return None
    if now - row.last_used_at >= TOUCH_EVERY:
        row.last_used_at = now
        session.flush()
    return user


def end_session(session: Session, token: str) -> None:
    if len(token) <= MAX_TOKEN_LENGTH:
        session.execute(delete(StaffSession).where(StaffSession.token_hash == hash_token(token)))


def end_all_sessions(session: Session, user_id: int) -> None:
    session.execute(delete(StaffSession).where(StaffSession.staff_user_id == user_id))


def delete_expired_sessions(session: Session, now: datetime) -> int:
    """Housekeeping for the worker: expired sessions already don't work."""
    deleted = session.scalars(
        delete(StaffSession)
        .where(or_(StaffSession.expires_at <= now, StaffSession.last_used_at <= now - IDLE_LIMIT))
        .returning(StaffSession.id)
    ).all()
    return len(deleted)
