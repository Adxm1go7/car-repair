"""What a customer can do from their booking link: see the booking, and cancel it while the
deposit would still come back. Customers can't reschedule; they call the garage.

Nothing here commits: the route does, or rolls back.
"""

from datetime import datetime
from typing import Literal

from sqlalchemy.orm import Session

from app.bookings.links import find_linked_booking
from app.bookings.rules import customer_can_cancel
from app.email.queue import queue_email
from app.models import Booking
from app.payments.provider import PaymentProvider
from app.payments.service import cancel_booking

RefusalReason = Literal["too_late", "not_cancellable"]


class LinkNotValid(Exception):
    """Unknown, expired or for another booking. The customer is told only that it isn't valid."""


class CancelRefused(Exception):
    def __init__(self, reason: RefusalReason) -> None:
        super().__init__(reason)
        self.reason: RefusalReason = reason


def view_from_link(session: Session, reference: str, token: str, now: datetime) -> Booking:
    booking = find_linked_booking(session, reference, token, now)
    if booking is None:
        raise LinkNotValid
    return booking


def cancel_from_link(
    session: Session,
    provider: PaymentProvider,
    reference: str,
    token: str,
    now: datetime,
    free_cancellation_hours: int,
) -> Booking:
    """Cancel the linked booking, refund its deposit and queue the cancellation email.

    The booking row is locked first, so a second press waits and then finds it cancelled.
    PaymentUnavailable propagates: the caller rolls back and nothing changes."""
    booking = find_linked_booking(session, reference, token, now, lock=True)
    if booking is None:
        raise LinkNotValid
    if booking.status != "confirmed":
        raise CancelRefused("not_cancellable")
    if not customer_can_cancel(booking.status, booking.start_at, now, free_cancellation_hours):
        raise CancelRefused("too_late")
    cancel_booking(
        session,
        provider,
        booking,
        now,
        by="customer",
        free_cancellation_hours=free_cancellation_hours,
    )
    queue_email(session, "cancellation", booking)
    return booking
