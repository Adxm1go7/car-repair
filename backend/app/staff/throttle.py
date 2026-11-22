"""The login lockout. Failed attempts are counted in the database, so the count survives a
restart and is shared by every API process.

An email with 10 failures, or an IP with 20, in the last 15 minutes is locked. A locked
login gets the same reply as a wrong password, so the lockout gives nothing away.
Nothing here commits.
"""

from datetime import datetime, timedelta
from typing import Final

from sqlalchemy import delete, func, select
from sqlalchemy.orm import InstrumentedAttribute, Session

from app.models import LoginAttempt

EMAIL_LIMIT: Final = 10
IP_LIMIT: Final = 20
WINDOW: Final = timedelta(minutes=15)
KEEP_FOR: Final = timedelta(days=1)
MAX_EMAIL_LENGTH: Final = 254  # the column's size


def normalise_email(email: str) -> str:
    return email.strip().lower()[:MAX_EMAIL_LENGTH]


def _failures(
    session: Session, column: InstrumentedAttribute[str], value: str, now: datetime
) -> int:
    count = session.scalar(
        select(func.count())
        .select_from(LoginAttempt)
        .where(
            column == value,
            LoginAttempt.succeeded.is_(False),
            LoginAttempt.at > now - WINDOW,
        )
    )
    return count or 0


def is_locked(
    session: Session, email: str, ip: str, now: datetime, *, skip_email_limit: bool = False
) -> bool:
    """`skip_email_limit`: count only the IP's failures (the live demo's public logins)."""
    if _failures(session, LoginAttempt.ip, ip, now) >= IP_LIMIT:
        return True
    if skip_email_limit:
        return False
    return _failures(session, LoginAttempt.email, normalise_email(email), now) >= EMAIL_LIMIT


def record_attempt(session: Session, email: str, ip: str, succeeded: bool, now: datetime) -> None:
    session.add(LoginAttempt(email=normalise_email(email), ip=ip, succeeded=succeeded, at=now))
    session.flush()


def delete_old_attempts(session: Session, now: datetime) -> int:
    deleted = session.scalars(
        delete(LoginAttempt).where(LoginAttempt.at < now - KEEP_FOR).returning(LoginAttempt.id)
    ).all()
    return len(deleted)
