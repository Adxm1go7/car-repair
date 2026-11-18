"""One row for every staff change, written in the same transaction as the change."""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.staff import StaffUser


class AuditEntry(Base):
    __tablename__ = "audit_entries"
    __table_args__ = (
        Index("ix_audit_entries_at", "at"),
        Index("ix_audit_entries_staff_user_id", "staff_user_id"),
        Index("ix_audit_entries_booking_reference", "booking_reference"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # None only for the create_admin command, which runs before anyone can log in.
    staff_user_id: Mapped[int | None] = mapped_column(ForeignKey("staff_users.id"))
    action: Mapped[str] = mapped_column(String(40))
    entity_type: Mapped[str] = mapped_column(String(20))
    entity_id: Mapped[int] = mapped_column(Integer)
    booking_reference: Mapped[str | None] = mapped_column(String(9))
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    reason: Mapped[str | None] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    staff_user: Mapped[StaffUser | None] = relationship()
