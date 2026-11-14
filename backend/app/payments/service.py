"""Completing deposits, refunding them, and cancelling a paid booking.

`complete_deposit` is the only code that marks a deposit paid or confirms a booking with
one. The webhook, the status poll, the demo endpoint, releasing a hold and the worker all
call it, and calling it again changes nothing.

Lock order everywhere: the booking row first, then its payment rows. Nothing here commits.
"""

import logging
from datetime import datetime

from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.models import Booking, Payment
from app.payments.provider import PaymentProvider, RefundStatus
from app.payments.rules import CancelledBy, deposit_refundable
from app.repositories.bookings import get_booking_for_update_by_id
from app.repositories.payments import (
    count_payments,
    find_payment,
    get_open_deposit,
    get_payment_for_update,
    paid_deposit,
)
from app.repositories.reservations import DEADLOCK_DETECTED, EXCLUSION_VIOLATION

log = logging.getLogger("app.payments")

_DEPOSIT_STATUS_FOR_REFUND: dict[RefundStatus, str] = {
    "pending": "refund_pending",
    "succeeded": "refunded",
    "failed": "refund_failed",
}


def _confirm(booking: Booking, now: datetime) -> None:
    booking.status = "confirmed"
    booking.deposit_status = "paid"
    booking.confirmed_at = now


def _take_time_back(session: Session, booking: Booking) -> bool:
    """Make an expired booking's reservation active again, if nobody has the time now."""
    try:
        with session.begin_nested():
            booking.reservation.active = True
            session.flush()
    except (IntegrityError, OperationalError) as error:
        if getattr(error.orig, "sqlstate", None) not in (EXCLUSION_VIOLATION, DEADLOCK_DETECTED):
            raise
        session.refresh(booking.reservation)
        return False
    return True


def complete_deposit(
    session: Session, provider: PaymentProvider, session_ref: str, now: datetime
) -> Booking | None:
    """Act on a payment, if the provider says it's paid. Returns the booking when it ends up
    confirmed by this payment; None when there was nothing (more) to do or it was refunded.

    The provider is asked every time, so neither a webhook body nor the browser is trusted.
    """
    found = find_payment(session, provider.name, session_ref)
    if found is None or found.kind != "deposit":
        log.warning("payment for an unknown session %s", session_ref)
        return None
    booking = get_booking_for_update_by_id(session, found.booking_id)
    deposit = get_payment_for_update(session, provider.name, session_ref)
    if booking is None or deposit is None:
        return None
    if deposit.status == "paid":
        return booking if booking.status == "confirmed" else None

    state = provider.get_checkout(session_ref)
    if not state.paid:
        return None
    deposit.status = "paid"
    deposit.payment_intent_ref = state.payment_intent_ref

    if booking.status == "held":
        _confirm(booking, now)  # its reservation is still active: nobody else could take it
    elif booking.status == "expired":
        if _take_time_back(session, booking):
            _confirm(booking, now)
        else:
            log.info("late payment for %s: the time is taken, refunding", booking.reference)
            refund_deposit(session, provider, deposit)
            session.flush()
            return None
    else:
        log.warning("payment for booking %s in status %s", booking.reference, booking.status)
        session.flush()
        return None
    session.flush()
    return booking


def refund_deposit(session: Session, provider: PaymentProvider, deposit: Payment) -> Payment:
    """Refund a paid deposit in full. PaymentUnavailable propagates: the caller rolls back."""
    if deposit.payment_intent_ref is None:
        raise ValueError("a deposit without a payment can't be refunded")
    attempt = count_payments(session, refund_of=deposit.id)
    state = provider.refund(
        payment_intent_ref=deposit.payment_intent_ref,
        amount_pence=deposit.amount_pence,
        # The provider's own session id: unique across databases (see start_checkout).
        idempotency_key=f"refund-{deposit.provider_ref}-{attempt}",
    )
    refund = Payment(
        booking_id=deposit.booking_id,
        kind="refund",
        provider=provider.name,
        provider_ref=state.refund_ref,
        amount_pence=deposit.amount_pence,
        currency=deposit.currency,
        status=state.status,
        refund_of=deposit.id,
    )
    session.add(refund)
    deposit.booking.deposit_status = _DEPOSIT_STATUS_FOR_REFUND[state.status]
    session.flush()
    return refund


def apply_refund_update(session: Session, provider: PaymentProvider, refund_ref: str) -> bool:
    """Bring a refund up to date from the provider. False if we have no such refund (yet)."""
    found = find_payment(session, provider.name, refund_ref)
    if found is None or found.kind != "refund":
        return False
    booking = get_booking_for_update_by_id(session, found.booking_id)
    refund = get_payment_for_update(session, provider.name, refund_ref)
    if booking is None or refund is None:
        return False
    state = provider.get_refund(refund_ref)
    refund.status = state.status
    booking.deposit_status = _DEPOSIT_STATUS_FOR_REFUND[state.status]
    session.flush()
    return True


def close_open_deposit(
    session: Session, provider: PaymentProvider, booking: Booking, now: datetime
) -> Booking | None:
    """Close the booking's open payment form. If a payment got in first, complete it instead,
    returning the booking when that confirmed it."""
    deposit = get_open_deposit(session, booking.id)
    if deposit is None:
        return None
    if provider.close_checkout(deposit.provider_ref):
        deposit.status = "expired"
        session.flush()
        return None
    return complete_deposit(session, provider, deposit.provider_ref, now)


def cancel_booking(
    session: Session,
    provider: PaymentProvider,
    booking: Booking,
    now: datetime,
    by: CancelledBy,
    free_cancellation_hours: int,
) -> None:
    """Cancel a booking and free its time, refunding the deposit when the rule says so.
    Milestones 6 (customer) and 7 (staff) call this."""
    booking.status = "cancelled"
    booking.reservation.active = False
    session.flush()
    if booking.deposit_status != "paid":
        return
    if not deposit_refundable(booking.start_at, now, free_cancellation_hours, by):
        return
    deposit = paid_deposit(session, booking.id)
    if deposit is not None:
        refund_deposit(session, provider, deposit)


def expire_open_deposit(session: Session, provider_name: str, session_ref: str) -> None:
    """The provider closed this payment form unpaid. The booking is left to the hold rules."""
    found = find_payment(session, provider_name, session_ref)
    if found is None or found.kind != "deposit":
        return
    get_booking_for_update_by_id(session, found.booking_id)
    deposit = get_payment_for_update(session, provider_name, session_ref)
    if deposit is not None and deposit.status == "open":
        deposit.status = "expired"
        session.flush()
