"""One attempt at a rate-limited public form, counted by action and visitor IP. The worker
prunes old rows."""

from datetime import datetime

from sqlalchemy import DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class RequestCount(Base):
    __tablename__ = "request_counts"
    __table_args__ = (Index("ix_request_counts_action_ip_at", "action", "ip", "at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    action: Mapped[str] = mapped_column(String(30))
    ip: Mapped[str] = mapped_column(String(45))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
