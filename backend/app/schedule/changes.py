"""Staff changes to a booking: move it, cancel it as the garage, and set the job's status.

Each one locks the booking row first, so two staff acting at once take turns and the
second sees the first's change. Each checks the action is allowed now, writes one audit
entry and queues any email, all in the caller's transaction. Nothing here commits.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, update
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.bookings.links import LINK_VALID_AFTER_END
from app.email.queue import queue_email
from app.models import Booking, BookingLink, EmailLog, StaffUser
from app.payments.provider import PaymentProvider
from app.payments.service import cancel_booking, close_open_deposit
from app.repositories.availability import load_policy
from app.repositories.bookings import get_booking_for_update, hold_has_expired
from app.repositories.reservations import DEADLOCK_DETECTED, EXCLUSION_VIOLATION, SlotUnavailable
from app.schedule.availability import infos_for_booking, staff_free_times
from app.schedule.status_rules import ACTION_TARGET, Action, StatusAction, booking_actions
from app.settings.lock import lock_shared
from app.staff.audit import record_audit


class NotAllowed(Exception):
    """The action isn't allowed on this booking now. `detail` is for the page."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


def locked_booking(session: Session, reference: str, action: Action, now: datetime) -> Booking:
    booking = get_booking_for_update(session, reference)
    if booking is None:
        raise LookupError(reference)
    if hold_has_expired(booking, now):
        # A request or an approval past its deadline: the worker is about to release it.
        raise NotAllowed("expired")
    if action not in booking_actions(
        booking.status, booking.start_at, booking.status_changed_at, now
    ):
        raise NotAllowed("not_allowed")
    return booking


def move_booking(
    session: Session,
    staff: StaffUser,
    reference: str,
    start: datetime,
    bay_id: int,
    reason: str | None,
    now: datetime,
) -> Booking:
    """Move the booking to `start` in `bay_id`, which must be one of the staff free times.
    Raises SlotUnavailable, NotAllowed or LookupError."""
    lock_shared(session)  # take turns with bay and opening-hours changes
    booking = locked_booking(session, reference, "move", now)
    before = move_reservation(session, booking, start, bay_id, now)
    queue_email(session, "moved", booking, {**previous(before), "reason": reason})
    record_audit(
        session,
        staff,
        "booking.move",
        "booking",
        booking.id,
        before=before,
        after=where_now(booking),
        reason=reason,
        booking_reference=booking.reference,
        now=now,
    )
    return booking


def where_now(booking: Booking) -> dict[str, str]:
    """The booking's time and bay, as the audit log and the move emails record them."""
    return {
        "start": booking.start_at.isoformat(),
        "end": booking.end_at.isoformat(),
        "bay": booking.reservation.bay.name,
    }


def move_reservation(
    session: Session, booking: Booking, start: datetime, bay_id: int, now: datetime
) -> dict[str, str]:
    """Move the locked booking to `start` in `bay_id`, which must be one of the staff free
    times, returning where it was. Its links follow the new end, and a reminder queued for
    the old time is dropped. Raises SlotUnavailable or NotAllowed("no_change")."""
    reservation = booking.reservation
    if start.astimezone(UTC) == booking.start_at.astimezone(UTC) and bay_id == reservation.bay_id:
        raise NotAllowed("no_change")

    policy = load_policy(session)
    day = start.astimezone(policy.zone).date()
    free = staff_free_times(
        session, infos_for_booking(booking), day, now, exclude_reservation_id=reservation.id
    )
    wanted = start.astimezone(UTC)
    slot = next((s for s in free.slots if s.start.astimezone(UTC) == wanted), None)
    if slot is None or bay_id not in slot.bay_ids:
        raise SlotUnavailable

    before = where_now(booking)
    occupied_until = slot.end.astimezone(UTC) + timedelta(minutes=policy.buffer_minutes)
    try:
        with session.begin_nested():
            reservation.bay_id = bay_id
            reservation.during = Range(wanted, occupied_until)
            session.flush()
    except (IntegrityError, OperationalError) as error:
        if getattr(error.orig, "sqlstate", None) not in (EXCLUSION_VIOLATION, DEADLOCK_DETECTED):
            raise
        session.refresh(reservation)
        raise SlotUnavailable from error  # taken since the engine looked
    session.refresh(reservation, ["bay"])

    booking.start_at = slot.start.astimezone(UTC)
    booking.end_at = slot.end.astimezone(UTC)
    session.execute(
        update(BookingLink)
        .where(BookingLink.booking_id == booking.id)
        .values(expires_at=booking.end_at + LINK_VALID_AFTER_END)
    )
    # A reminder queued for the old time would go out now with the new one, and the
    # one-reminder index would then stop the proper one. Drop it; the worker re-queues.
    session.execute(
        delete(EmailLog).where(
            EmailLog.booking_id == booking.id,
            EmailLog.template == "reminder",
            EmailLog.status == "queued",
        )
    )
    session.flush()
    return before


def previous(before: dict[str, str]) -> dict[str, str]:
    return {
        "previous_start": before["start"],
        "previous_end": before["end"],
        "previous_bay": before["bay"],
    }


def garage_cancel(
    session: Session,
    provider: PaymentProvider,
    staff: StaffUser,
    reference: str,
    reason: str | None,
    now: datetime,
    free_cancellation_hours: int,
) -> Booking:
    """Cancel as the garage: a paid deposit is always refunded. PaymentUnavailable
    propagates, and the caller rolls back."""
    booking = locked_booking(session, reference, "cancel", now)
    if booking.status == "awaiting_deposit":
        # Close the deposit's form first, so the customer can't pay for a cancelled booking.
        # If a payment got in, it confirmed the booking, and the cancel refunds it.
        close_open_deposit(session, provider, booking, now)
    before = {"status": booking.status, "deposit_status": booking.deposit_status}
    cancel_booking(session, provider, booking, now, "garage", free_cancellation_hours)
    queue_email(session, "garage_cancellation", booking, {"reason": reason})
    record_audit(
        session,
        staff,
        "booking.cancel",
        "booking",
        booking.id,
        before=before,
        after={"status": booking.status, "deposit_status": booking.deposit_status},
        reason=reason,
        booking_reference=booking.reference,
        now=now,
    )
    return booking


def change_status(
    session: Session, staff: StaffUser, reference: str, action: StatusAction, now: datetime
) -> Booking:
    """Start, complete, no-show, or undo one of those. A no-show keeps the deposit and the
    booked time, and sends no email."""
    # An undo makes the booking count again, so it takes turns with bay and hours changes;
    # before the row lock, the same order as everywhere else.
    lock_shared(session)
    booking = locked_booking(session, reference, action, now)
    if action in ("undo_no_show", "undo_complete") and not booking.reservation.bay.active:
        # Back to an active status in a bay that's out of use: staff move it instead.
        raise NotAllowed("not_allowed")
    before = {"status": booking.status}
    booking.status = ACTION_TARGET[action]
    booking.status_changed_at = now
    session.flush()
    record_audit(
        session,
        staff,
        "booking.status",
        "booking",
        booking.id,
        before=before,
        after={"status": booking.status},
        booking_reference=booking.reference,
        now=now,
    )
    return booking
