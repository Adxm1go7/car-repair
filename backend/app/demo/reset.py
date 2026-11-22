"""The live demo's nightly reset: empty every data table, then run the normal seed.

It takes the hours-and-bays lock exclusive first, so it waits (briefly) for any booking being
made or moved. Then it locks every table at once with NOWAIT: if anyone is still using one
(a booking that has read the settings but not yet taken the shared lock), it gives up at
once rather than deadlocking with them or making every new request queue behind it, and
the worker tries again a few seconds later. One TRUNCATE covers every table the models know,
which leaves alembic_version alone. ID sequences carry on (CONTINUE IDENTITY), so a late
Stripe webhook for a wiped booking can never match a new row that reused its ID; the
webhook ignores sessions it doesn't know.
"""

from datetime import datetime, time, timedelta
from typing import Final
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import Base
from app.seed import seed
from app.settings.lock import lock_exclusive

RESET_AT: Final = time(3, 0)
RESET_ZONE: Final = ZoneInfo("Europe/London")
# A worker that starts this soon after RESET_AT still runs that night's reset.
LATE_START: Final = timedelta(minutes=10)


def latest_reset_time(now: datetime, zone: ZoneInfo) -> datetime:
    """The most recent RESET_AT in `zone` at or before `now`."""
    local = now.astimezone(zone)
    today = datetime.combine(local.date(), RESET_AT, tzinfo=zone)
    return (
        today
        if today <= local
        else datetime.combine(local.date() - timedelta(days=1), RESET_AT, tzinfo=zone)
    )


def reset_due(last_reset: datetime | None, now: datetime, zone: ZoneInfo) -> bool:
    """True once after each RESET_AT. With no reset yet (the worker just started), only
    within LATE_START of it, so a restart in the day doesn't wipe the demo."""
    latest = latest_reset_time(now, zone)
    if last_reset is None:
        return now - latest < LATE_START
    return latest > last_reset


def reset_demo(session: Session, *, wait_seconds: int = 10) -> None:
    """Empty every data table and seed it again, demo logins included. The caller commits.
    Raises OperationalError, changing nothing, if bookings in progress don't finish within
    `wait_seconds` or a table is in use."""
    session.execute(text(f"SET LOCAL lock_timeout = '{int(wait_seconds)}s'"))
    lock_exclusive(session)
    tables = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
    session.execute(text(f"LOCK TABLE {tables} IN ACCESS EXCLUSIVE MODE NOWAIT"))
    session.execute(text(f"TRUNCATE {tables} CONTINUE IDENTITY CASCADE"))  # noqa: S608 - our own table names
    seed(session, sample_accounts=True)
