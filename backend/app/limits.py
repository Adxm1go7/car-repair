"""Rate limits on the public forms. Each attempt is counted in the database, by action and
visitor IP, so the count is shared by every API process and survives a restart.

An attempt under the limit is recorded and committed before the route does anything, so it
counts even if the route then fails. An attempt at the limit is refused and not recorded.
The limits are off in development, where all local traffic comes from one address.
"""

import math
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Final, Literal

from fastapi import Request
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import RequestCount
from app.staff.deps import NowDep, SessionDep, client_ip

Action = Literal["hold", "pay", "request", "enquiry", "link"]

LIMITS: Final[dict[Action, tuple[int, timedelta]]] = {
    "hold": (30, timedelta(minutes=15)),
    "pay": (10, timedelta(minutes=15)),
    "request": (5, timedelta(minutes=60)),
    "enquiry": (5, timedelta(minutes=60)),
    "link": (30, timedelta(minutes=15)),
}
KEEP_FOR: Final = timedelta(days=1)
LIMITED_ENVIRONMENTS: Final = ("test", "production")
TOO_MANY: Final = "Too many attempts. Please wait a few minutes and try again."


class TooManyAttempts(Exception):
    def __init__(self, retry_after: int) -> None:
        super().__init__(TOO_MANY)
        self.retry_after = retry_after


def retry_after(oldest: datetime, window: timedelta, now: datetime) -> int:
    """Whole seconds until the oldest counted attempt leaves the window; at least 1."""
    return max(1, math.ceil((oldest + window - now).total_seconds()))


def check_and_record(session: Session, action: Action, ip: str, now: datetime) -> None:
    """Refuse (TooManyAttempts) at the limit; otherwise record this attempt and commit."""
    limit, window = LIMITS[action]
    count, oldest = session.execute(
        select(func.count(), func.min(RequestCount.at)).where(
            RequestCount.action == action,
            RequestCount.ip == ip,
            RequestCount.at > now - window,
        )
    ).one()
    if count >= limit:
        raise TooManyAttempts(retry_after(oldest, window, now))
    session.add(RequestCount(action=action, ip=ip, at=now))
    session.commit()


def limited(action: Action) -> Callable[[Request, Session, datetime], None]:
    """A route dependency that counts this attempt, or refuses it with a 429."""

    def check(request: Request, session: SessionDep, now: NowDep) -> None:
        if request.app.state.config.environment not in LIMITED_ENVIRONMENTS:
            return
        check_and_record(session, action, client_ip(request), now)

    return check


def delete_old_counts(session: Session, now: datetime) -> int:
    deleted = session.scalars(
        delete(RequestCount).where(RequestCount.at < now - KEEP_FOR).returning(RequestCount.id)
    ).all()
    return len(deleted)
