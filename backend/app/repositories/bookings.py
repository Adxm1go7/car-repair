"""Bookings in the database, and the one rule for when a hold has expired."""

from datetime import datetime
from typing import Final

from sqlalchemy import ColumnElement, and_, select, update
from sqlalchemy.orm import Session, selectinload

from app.email.message import EmailTemplate
from app.email.queue import queue_email
from app.models import Booking, Reservation
from app.models.booking import WAITING_STATUSES

# --- the expiry rule -------------------------------------------------------------
# A hold has expired when it is still waiting (held, a request, or an approval waiting for
# its deposit) and its deadline, hold_expires_at, has arrived.
# These two functions are the same rule, in SQL and in Python. They must always agree.


def expired_hold(now: datetime) -> ColumnElement[bool]:
    return and_(Booking.status.in_(WAITING_STATUSES), Booking.hold_expires_at <= now)


def hold_has_expired(booking: Booking, now: datetime) -> bool:
    return (
        booking.status in WAITING_STATUSES
        and booking.hold_expires_at is not None
        and booking.hold_expires_at <= now
    )


# What the customer is told when a request or an approval runs out. A plain hold's
# customer is still on the page, so they get no email.
_EXPIRY_EMAIL: Final[dict[str, EmailTemplate]] = {
    "pending_approval": "request_expired",
    "awaiting_deposit": "deposit_expired",
}


# --- releasing -------------------------------------------------------------------


def release_hold(session: Session, booking: Booking) -> None:
    """Mark the booking expired and free its bay time, emailing the customer when it was a
    request or an approval. History is kept. Doesn't commit."""
    template = _EXPIRY_EMAIL.get(booking.status)
    if template is not None:
        queue_email(session, template, booking)
    booking.status = "expired"
    booking.reservation.active = False
    session.flush()


def release_expired_holds(session: Session, now: datetime) -> int:
    """Release every hold that has expired at `now`, returning how many. Doesn't commit.

    The WHERE clause re-checks the rule row by row, so a hold confirmed a moment ago
    (or one another sweep just released) is left alone. A request or an approval that runs
    out gets its email queued, once: a second sweep finds nothing waiting.
    """
    before = select(Booking.id, Booking.status.label("was")).where(expired_hold(now)).subquery()
    released = session.execute(
        update(Booking)
        .where(Booking.id == before.c.id, expired_hold(now))
        .values(status="expired")
        .returning(Booking.id, Booking.reservation_id, before.c.was)
        .execution_options(synchronize_session=False)
    ).all()
    reservation_ids = [row.reservation_id for row in released]
    if reservation_ids:
        session.execute(
            update(Reservation)
            .where(Reservation.id.in_(reservation_ids))
            .values(active=False)
            .execution_options(synchronize_session=False)
        )
    # Objects already loaded in this session may now be stale.
    session.expire_all()
    emails = {row.id: _EXPIRY_EMAIL[row.was] for row in released if row.was in _EXPIRY_EMAIL}
    if emails:
        for booking in session.scalars(
            select(Booking).where(Booking.id.in_(emails)).order_by(Booking.id)
        ):
            queue_email(session, emails[booking.id], booking)
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
