"""The outbox: the worker sends queued emails from email_log, one row at a time.

Each row is locked with SKIP LOCKED, so two workers never send the same email, and each is
committed on its own, so one bad address never holds up the rest. A booking link or a
set-password token is made in the same transaction as the send; if the send fails, the
rollback drops it too.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.bookings.links import create_link
from app.email.message import EmailTemplate, OutgoingEmail, StaffTemplate
from app.email.render import EmailContext, StaffEmailContext, render_email, render_staff_email
from app.email.sender import EmailSender, EmailUnavailable
from app.models import Booking, EmailLog, StaffUser
from app.repositories.availability import (
    load_deposit_pence,
    load_free_cancellation_hours,
    load_policy,
)
from app.repositories.catalogue import get_setting
from app.repositories.payments import paid_deposit
from app.staff.links import VALID_FOR, Purpose, issue_password_token, set_password_url

log = logging.getLogger("app.email")

RETRY_DELAYS: Final[tuple[timedelta, ...]] = (
    timedelta(minutes=1),
    timedelta(minutes=5),
    timedelta(minutes=15),
    timedelta(minutes=60),
)
MAX_ATTEMPTS: Final = 5
# What the booking's status must still be for the email to be worth sending.
_APPLIES_TO: Final[dict[EmailTemplate, str]] = {
    "confirmation": "confirmed",
    "reminder": "confirmed",
    "cancellation": "cancelled",
    "moved": "confirmed",
    "garage_cancellation": "cancelled",
    "request_received": "pending_approval",
    "approved": "awaiting_deposit",
    "proposed": "awaiting_deposit",
    "declined": "cancelled",
    "request_expired": "expired",
    "deposit_expired": "expired",
}
_HAS_LINK: Final[frozenset[EmailTemplate]] = frozenset(
    {"confirmation", "reminder", "moved", "request_received", "approved", "proposed"}
)
_PURPOSE: Final[dict[StaffTemplate, Purpose]] = {
    "staff_invite": "invite",
    "password_reset": "reset",
}


def next_attempt_delay(attempts: int) -> timedelta:
    """How long to wait after the `attempts`-th failed try."""
    return RETRY_DELAYS[min(attempts, len(RETRY_DELAYS)) - 1]


def email_still_applies(template: EmailTemplate, booking_status: str) -> bool:
    return _APPLIES_TO[template] == booking_status


def link_url(base_url: str, reference: str, token: str) -> str:
    # The token goes in the fragment, so browsers never send it to a server or put it in logs.
    return f"{base_url.rstrip('/')}/booking/{reference}#t={token}"


def _when(saved: dict[str, Any], key: str) -> datetime | None:
    value = saved.get(key)
    return datetime.fromisoformat(value) if isinstance(value, str) else None


def _context(
    session: Session,
    booking: Booking,
    url: str | None,
    now: datetime,
    saved: dict[str, Any] | None = None,
) -> EmailContext:
    """`saved` is the email row's context: what a garage change said when it was queued."""
    saved = saved or {}
    reason = saved.get("reason")
    previous_bay = saved.get("previous_bay")
    deposit = paid_deposit(session, booking.id)
    garage = get_setting(session, "garage_contact")
    return EmailContext(
        reference=booking.reference,
        customer_name=booking.customer_name or "",
        start=booking.start_at,
        end=booking.end_at,
        zone=load_policy(session).zone,
        services=[item.service_name for item in booking.items],
        registration=booking.car_registration or "",
        make=booking.car_make or "",
        model=booking.car_model or "",
        deposit_status=booking.deposit_status,
        deposit_pence=deposit.amount_pence if deposit is not None else 0,
        free_cancellation_until=booking.start_at
        - timedelta(hours=load_free_cancellation_hours(session)),
        garage=garage if isinstance(garage, dict) else {},
        link_url=url,
        now=now,
        reason=reason if isinstance(reason, str) else None,
        previous_start=_when(saved, "previous_start"),
        previous_end=_when(saved, "previous_end"),
        previous_bay=previous_bay if isinstance(previous_bay, str) else None,
        deadline=booking.hold_expires_at,
        deposit_due_pence=load_deposit_pence(session),
    )


def _next_due(session: Session, now: datetime) -> EmailLog | None:
    return session.scalars(
        select(EmailLog)
        .where(EmailLog.status == "queued", EmailLog.next_attempt_at <= now)
        .order_by(EmailLog.next_attempt_at, EmailLog.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).one_or_none()


def _record_failure(session: Session, email_id: int, error: Exception, now: datetime) -> None:
    session.rollback()  # drops the link made for this send
    email = session.get(EmailLog, email_id, with_for_update=True)
    if email is None:
        return
    email.attempts += 1
    email.last_error = str(error)[:500]
    if email.attempts >= MAX_ATTEMPTS:
        email.status = "failed"
        log.error("gave up on email %d after %d tries", email.id, email.attempts)
    else:
        email.next_attempt_at = now + next_attempt_delay(email.attempts)
        log.warning("email %d failed, trying again at %s", email.id, email.next_attempt_at)
    session.commit()


def _prepare(
    session: Session, email: EmailLog, now: datetime, base_url: str
) -> OutgoingEmail | None:
    """Render a due email, making its link's token if it has one. None: it no longer applies
    (the booking moved on, or the staff member was removed) and must not be sent."""
    if email.staff_user_id is not None:
        return _prepare_staff(session, email, now, base_url)
    template: EmailTemplate = email.template  # type: ignore[assignment]  # checked in the DB
    booking = email.booking
    if booking is None or not email_still_applies(template, booking.status):
        return None
    url = None
    if template in _HAS_LINK:
        url = link_url(base_url, booking.reference, create_link(session, booking))
    context = _context(session, booking, url, now, email.context)
    return render_email(template, email.recipient, context)


def _prepare_staff(
    session: Session, email: EmailLog, now: datetime, base_url: str
) -> OutgoingEmail | None:
    template: StaffTemplate = email.template  # type: ignore[assignment]  # checked in the DB
    user: StaffUser | None = email.staff_user
    if user is None or not user.active:
        return None
    purpose = _PURPOSE[template]
    token = issue_password_token(session, user, purpose, now)
    garage = get_setting(session, "garage_contact")
    context = StaffEmailContext(
        name=user.name,
        garage=garage if isinstance(garage, dict) else {},
        link_url=set_password_url(base_url, token),
        valid_for=VALID_FOR[purpose],
    )
    return render_staff_email(template, email.recipient, context)


def send_due_emails(
    session: Session, sender: EmailSender, now: datetime, base_url: str, batch: int = 20
) -> int:
    """Send up to `batch` queued emails that are due at `now`. Returns how many were sent."""
    sent = 0
    for _ in range(batch):
        email = _next_due(session, now)
        if email is None:
            break
        email_id = email.id
        message = _prepare(session, email, now, base_url)
        if message is None:
            email.status = "skipped"
            session.commit()
            continue
        try:
            sender.send(message)
        except EmailUnavailable as error:
            _record_failure(session, email_id, error, now)
            continue
        email.status = "sent"
        email.sent_at = now
        session.commit()
        sent += 1
    return sent
