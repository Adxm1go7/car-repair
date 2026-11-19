"""What a customer can do from their booking link: see the booking, pay the deposit once
staff approve a request, and cancel it while the deposit would still come back (a request
or an unpaid approval at any time). Customers can't reschedule; they call the garage.

Nothing here commits: the route does, or rolls back.
"""

from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.bookings.links import find_linked_booking
from app.bookings.rules import customer_can_cancel
from app.bookings.service import CheckoutResult, open_deposit_form, settle_waiting
from app.email.queue import queue_email
from app.models import Booking
from app.payments.provider import PaymentProvider
from app.payments.service import cancel_booking, close_open_deposit
from app.settings.lock import lock_shared

RefusalReason = Literal["too_late", "not_cancellable"]


class LinkNotValid(Exception):
    """Unknown, expired or for another booking. The customer is told only that it isn't valid."""


class CancelRefused(Exception):
    def __init__(self, reason: RefusalReason) -> None:
        super().__init__(reason)
        self.reason: RefusalReason = reason


class NothingToPay(Exception):
    """The booking isn't waiting for its deposit (not approved yet, paid, or run out)."""


def _waiting_booking(
    session: Session, provider: PaymentProvider, reference: str, token: str, now: datetime
) -> Booking:
    # Settling may complete a payment, which takes turns with bay and hours changes: take
    # that lock before the row lock, the same order as everywhere else.
    lock_shared(session)
    booking = find_linked_booking(session, reference, token, now, lock=True)
    if booking is None:
        raise LinkNotValid
    settle_waiting(session, provider, booking, now)
    return booking


def view_from_link(
    session: Session, provider: PaymentProvider, reference: str, token: str, now: datetime
) -> Booking:
    """The linked booking, brought up to date. The caller commits what settling did."""
    return _waiting_booking(session, provider, reference, token, now)


def pay_from_link(
    session: Session,
    provider: PaymentProvider,
    reference: str,
    token: str,
    now: datetime,
    *,
    amount_pence: int,
    zone: ZoneInfo,
) -> CheckoutResult:
    """Open (or reopen) the deposit's payment form for an approved booking. Raises
    LinkNotValid or NothingToPay (the caller commits what settling did);
    PaymentUnavailable propagates, and the caller rolls back."""
    booking = _waiting_booking(session, provider, reference, token, now)
    if booking.status != "awaiting_deposit":
        raise NothingToPay
    return open_deposit_form(session, provider, booking, now, amount_pence=amount_pence, zone=zone)


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
    if booking.status == "awaiting_deposit":
        # Close the form first, so the deposit can't be paid for a cancelled booking. If a
        # payment got in, the booking is confirmed now and the usual rules apply below.
        close_open_deposit(session, provider, booking, now)
    if booking.status not in ("confirmed", "pending_approval", "awaiting_deposit"):
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
