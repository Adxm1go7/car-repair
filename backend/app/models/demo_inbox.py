"""Demo site only: the emails the worker would have sent, kept for the Demo inbox page.

Unlike email_log, this stores the rendered body, booking-link tokens included, on purpose:
the inbox is how visitors to the live demo use their "manage my booking" links. Nothing is
written here unless DEMO_SITE is on, and the nightly reset empties it.
"""

from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DemoInboxEmail(Base):
    __tablename__ = "demo_inbox"
    __table_args__ = (Index("ix_demo_inbox_recipient_id", "recipient", "id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    template: Mapped[str] = mapped_column(String(30))
    recipient: Mapped[str] = mapped_column(String(254))
    subject: Mapped[str] = mapped_column(String(300))
    text: Mapped[str] = mapped_column(Text)
    html: Mapped[str] = mapped_column(Text)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
