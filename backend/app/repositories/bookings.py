"""Bookings in the database, and the one rule for when a hold has expired."""

from datetime import datetime

from sqlalchemy import ColumnElement, and_, select, update
from sqlalchemy.orm import Session, selectinload

from app.models import Booking, Reservation

# --- the expiry rule -------------------------------------------------------------
# A hold has expired when it is still "held" and its expiry time has arrived.
# These two functions are the same rule, in SQL and in Python. They must always agree.


def expired_hold(now: datetime) -> ColumnElement[bool]:
    return and_(Booking.status == "held", Booking.hold_expires_at <= now)


def hold_has_expired(booking: Booking, now: datetime) -> bool:
    return (
        booking.status == "held"
        and booking.hold_expires_at is not None
        and booking.hold_expires_at <= now
    )


# --- releasing -------------------------------------------------------------------


def release_hold(session: Session, booking: Booking) -> None:
    """Mark the booking expired and free its bay time. History is kept. Doesn't commit."""
    booking.status = "expired"
    booking.reservation.active = False
    session.flush()


def release_expired_holds(session: Session, now: datetime) -> int:
    """Release every hold that has expired at `now`, returning how many. Doesn't commit.

    The WHERE clause re-checks the rule row by row, so a hold confirmed a moment ago
    (or one another sweep just released) is left alone.
    """
    reservation_ids = session.scalars(
        update(Booking)
        .where(expired_hold(now))
        .values(status="expired")
        .returning(Booking.reservation_id)
        .execution_options(synchronize_session=False)
    ).all()
    if reservation_ids:
        session.execute(
            update(Reservation)
            .where(Reservation.id.in_(reservation_ids))
            .values(active=False)
            .execution_options(synchronize_session=False)
        )
    # Objects already loaded in this session may now be stale.
    session.expire_all()
    return len(reservation_ids)


# --- loading ---------------------------------------------------------------------


def get_booking_for_update(session: Session, reference: str) -> Booking | None:
    """The booking, locked until the transaction ends, with its items and reservation."""
    statement = (
        select(Booking)
        .where(Booking.reference == reference)
        .options(selectinload(Booking.items), selectinload(Booking.reservation))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return session.scalars(statement).one_or_none()


def get_booking_for_update_by_id(session: Session, booking_id: int) -> Booking | None:
    """Like get_booking_for_update, by id: for code that starts from a payment row."""
    statement = (
        select(Booking)
        .where(Booking.id == booking_id)
        .options(selectinload(Booking.items), selectinload(Booking.reservation))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return session.scalars(statement).one_or_none()
