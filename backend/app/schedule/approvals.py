"""Staff answer a booking request: approve it, propose another time, or decline it.

Approving (or proposing a time) asks the customer for the deposit: the booking waits in
"awaiting deposit" until they pay or its payment deadline passes. Each action takes turns
with bay and hours changes, locks the booking, checks it's allowed now, writes one audit
entry and queues the customer's email, all in the caller's transaction. Nothing here commits.
"""

from datetime import datetime

from sqlalchemy.orm import Session

from app.bookings.approval import enough_time_to_pay, payment_deadline
from app.email.queue import queue_email
from app.models import Booking, StaffUser
from app.payments.provider import PaymentProvider
from app.payments.service import close_open_deposit
from app.repositories.availability import load_approval_rules, load_policy
from app.schedule.changes import NotAllowed, locked_booking, move_reservation, previous, where_now
from app.settings.lock import lock_shared
from app.staff.audit import record_audit


def _ask_for_deposit(session: Session, booking: Booking, now: datetime) -> None:
    """Start the time to pay, or refuse with "too_soon" when it would be too short."""
    rules = load_approval_rules(session)
    cutoff = load_policy(session).cutoff_minutes
    if not enough_time_to_pay(now, booking.start_at, rules, cutoff):
        raise NotAllowed("too_soon")
    booking.status = "awaiting_deposit"
    booking.hold_expires_at = payment_deadline(now, booking.start_at, rules, cutoff)
    session.flush()


def approve_booking(session: Session, staff: StaffUser, reference: str, now: datetime) -> Booking:
    """Approve the request as asked. Raises NotAllowed or LookupError."""
    lock_shared(session)  # take turns with bay and opening-hours changes
    booking = locked_booking(session, reference, "approve", now)
    before = {"status": booking.status}
    _ask_for_deposit(session, booking, now)
    queue_email(session, "approved", booking)
    record_audit(
        session,
        staff,
        "booking.approve",
        "booking",
        booking.id,
        before=before,
        after={"status": booking.status},
        booking_reference=booking.reference,
        now=now,
    )
    return booking


def propose_booking(
    session: Session,
    provider: PaymentProvider,
    staff: StaffUser,
    reference: str,
    start: datetime,
    bay_id: int,
    reason: str | None,
    now: datetime,
) -> Booking:
    """Move the request (or an approval not paid yet) to a time agreed on the phone, and
    ask for the deposit for it. An approval's open payment form is closed, so the old time
    can't be paid for. Raises SlotUnavailable, NotAllowed or LookupError; PaymentUnavailable
    propagates, and the caller rolls back."""
    lock_shared(session)
    booking = locked_booking(session, reference, "propose", now)
    rules = load_approval_rules(session)
    cutoff = load_policy(session).cutoff_minutes
    if not enough_time_to_pay(now, start, rules, cutoff):
        raise NotAllowed("too_soon")
    if booking.status == "awaiting_deposit" and close_open_deposit(session, provider, booking, now):
        # A payment got in first and confirmed the old time: it's a normal booking now.
        raise NotAllowed("not_allowed")
    before = move_reservation(session, booking, start, bay_id, now)
    _ask_for_deposit(session, booking, now)
    queue_email(session, "proposed", booking, {**previous(before), "reason": reason})
    record_audit(
        session,
        staff,
        "booking.propose",
        "booking",
        booking.id,
        before=before,
        after=where_now(booking),
        reason=reason,
        booking_reference=booking.reference,
        now=now,
    )
    return booking


def decline_booking(
    session: Session, staff: StaffUser, reference: str, reason: str | None, now: datetime
) -> Booking:
    """Turn the request down and free its time. Nothing was paid, so nothing is refunded.
    Raises NotAllowed or LookupError."""
    lock_shared(session)
    booking = locked_booking(session, reference, "decline", now)
    before = {"status": booking.status}
    booking.status = "cancelled"
    booking.reservation.active = False
    session.flush()
    queue_email(session, "declined", booking, {"reason": reason})
    record_audit(
        session,
        staff,
        "booking.decline",
        "booking",
        booking.id,
        before=before,
        after={"status": booking.status},
        reason=reason,
        booking_reference=booking.reference,
        now=now,
    )
    return booking
