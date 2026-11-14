"""Emails to customers. Each row is one email: the queue the worker sends from, and the log.

No body is stored. The worker renders the email when it sends it, so a booking link's
token never touches the database. The partial unique index makes a second reminder for one
booking impossible, whatever the code does.
"""

from datetime import datetime
from typing import Final

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.booking import Booking

EMAIL_TEMPLATES: Final[tuple[str, ...]] = ("confirmation", "reminder", "cancellation")
# skipped: the booking changed before it went out (a reminder for a cancelled booking).
EMAIL_STATUSES: Final[tuple[str, ...]] = ("queued", "sent", "failed", "skipped")


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


class EmailLog(Base):
    __tablename__ = "email_log"
    __table_args__ = (
        CheckConstraint(f"template IN ({_quoted(EMAIL_TEMPLATES)})", name="template_valid"),
        CheckConstraint(f"status IN ({_quoted(EMAIL_STATUSES)})", name="status_valid"),
        CheckConstraint("attempts >= 0", name="attempts_non_negative"),
        Index("ix_email_log_status_next_attempt_at", "status", "next_attempt_at"),
        Index(
            "ux_email_log_one_reminder",
            "booking_id",
            unique=True,
            postgresql_where=text("template = 'reminder'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    template: Mapped[str] = mapped_column(String(20))
    booking_id: Mapped[int | None] = mapped_column(ForeignKey("bookings.id"))
    recipient: Mapped[str] = mapped_column(String(254))
    status: Mapped[str] = mapped_column(String(10), server_default="queued")
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_error: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    booking: Mapped[Booking | None] = relationship()
