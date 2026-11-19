"""One lock for "the garage's hours and bays".

Anything that creates or moves a booking takes it shared, so bookings never wait on each
other. Taking a bay out of use and saving or deleting opening hours take it exclusive and
then run their clash check, so a booking made at the same moment is either seen by the
check or sees the change. Transaction-level: it goes when the transaction ends.
"""

from typing import Final

from sqlalchemy import text
from sqlalchemy.orm import Session

HOURS_AND_BAYS_LOCK: Final = 0x6761726167  # "garag"


def lock_shared(session: Session) -> None:
    session.execute(text("SELECT pg_advisory_xact_lock_shared(:key)"), {"key": HOURS_AND_BAYS_LOCK})


def lock_exclusive(session: Session) -> None:
    session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": HOURS_AND_BAYS_LOCK})
