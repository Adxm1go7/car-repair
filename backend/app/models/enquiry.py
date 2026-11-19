"""Enquiries: a customer describes a problem they can't name, with no time slot and no payment.
Staff either book it in (it becomes a booking, linked here) or decline it."""

from datetime import datetime
from typing import Final

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.booking import Booking
from app.models.staff import StaffUser

ENQUIRY_STATUSES: Final[tuple[str, ...]] = ("new", "converted", "declined")
_STATUS_LIST = ", ".join(f"'{status}'" for status in ENQUIRY_STATUSES)


class Enquiry(Base):
    __tablename__ = "enquiries"
    __table_args__ = (
        CheckConstraint(f"status IN ({_STATUS_LIST})", name="status_valid"),
        CheckConstraint(
            "(status = 'converted') = (booking_id IS NOT NULL)", name="booking_only_when_converted"
        ),
        CheckConstraint(
            "(status = 'new') = (handled_at IS NULL)"
            " AND (handled_at IS NULL) = (handled_by IS NULL)",
            name="handled_unless_new",
        ),
        Index("ix_enquiries_status_created_at", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(String(10), server_default="new")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    customer_name: Mapped[str] = mapped_column(String(100))
    customer_phone: Mapped[str] = mapped_column(String(20))
    customer_email: Mapped[str] = mapped_column(String(254))
    car_registration: Mapped[str] = mapped_column(String(8))
    car_make: Mapped[str] = mapped_column(String(50))
    car_model: Mapped[str] = mapped_column(String(50))
    description: Mapped[str] = mapped_column(Text)
    handled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    handled_by: Mapped[int | None] = mapped_column(ForeignKey("staff_users.id"))
    decline_reason: Mapped[str | None] = mapped_column(String(500))
    booking_id: Mapped[int | None] = mapped_column(ForeignKey("bookings.id"), unique=True)

    handler: Mapped[StaffUser | None] = relationship()
    booking: Mapped[Booking | None] = relationship()
