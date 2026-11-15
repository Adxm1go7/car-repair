"""Reminders: the worker queues one for each confirmed booking once it's close to its start.

A booking confirmed inside the reminder window gets none: its confirmation email was just
sent and says the same things. The partial unique index on email_log means a second
reminder can't be queued, even by two workers at once.
"""

from datetime import datetime, timedelta

from sqlalchemy import exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.email.queue import queue_email
from app.models import Booking, EmailLog

ONE_REMINDER_INDEX = "ux_email_log_one_reminder"


def queue_due_reminders(session: Session, now: datetime, hours_before: int) -> int:
    """Queue a reminder for every confirmed booking starting within `hours_before` hours of
    `now` that doesn't have one yet. Returns how many were queued. Doesn't commit."""
    window = timedelta(hours=hours_before)
    has_reminder = exists().where(
        EmailLog.booking_id == Booking.id, EmailLog.template == "reminder"
    )
    due = session.scalars(
        select(Booking)
        .where(
            Booking.status == "confirmed",
            Booking.start_at <= now + window,
            Booking.start_at > now,
            Booking.confirmed_at < Booking.start_at - window,
            ~has_reminder,
        )
        .order_by(Booking.start_at)
    ).all()
    queued = 0
    for booking in due:
        try:
            with session.begin_nested():
                queue_email(session, "reminder", booking)
        except IntegrityError as error:
            if getattr(getattr(error.orig, "diag", None), "constraint_name", None) != (
                ONE_REMINDER_INDEX
            ):
                raise
            continue  # another worker queued it first
        queued += 1
    return queued
