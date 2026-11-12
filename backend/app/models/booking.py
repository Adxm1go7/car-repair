"""A customer's booking, and a snapshot of each service on it.

The bay and the occupied time (including the bay buffer) live on the linked reservation.
`start_at` and `end_at` here are what the customer sees: the real end, without the buffer.
"""

from datetime import datetime
from typing import Final

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.catalogue import Service
from app.models.reservation import Reservation

BOOKING_STATUSES: Final[tuple[str, ...]] = (
    "held",
    "pending_approval",
    "confirmed",
    "in_progress",
    "completed",
    "cancelled",
    "no_show",
    "expired",
)

_STATUS_LIST = ", ".join(f"'{status}'" for status in BOOKING_STATUSES)
_DETAIL_COLUMNS = (
    "customer_name",
    "customer_phone",
    "customer_email",
    "car_registration",
    "car_make",
    "car_model",
)


class Booking(Base):
    __tablename__ = "bookings"
    __table_args__ = (
        CheckConstraint(f"status IN ({_STATUS_LIST})", name="status_valid"),
        CheckConstraint("start_at < end_at", name="start_before_end"),
        CheckConstraint("status <> 'held' OR hold_expires_at IS NOT NULL", name="held_has_expiry"),
        CheckConstraint("status <> 'held' OR hold_token_hash IS NOT NULL", name="held_has_token"),
        CheckConstraint(
            "status <> 'confirmed' OR ("
            + " AND ".join(f"{column} IS NOT NULL" for column in _DETAIL_COLUMNS)
            + ")",
            name="confirmed_has_details",
        ),
        Index("ix_bookings_status_hold_expires_at", "status", "hold_expires_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    reference: Mapped[str] = mapped_column(String(9), unique=True)
    reservation_id: Mapped[int] = mapped_column(ForeignKey("reservations.id"), unique=True)
    status: Mapped[str] = mapped_column(String(20))
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    hold_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    hold_token_hash: Mapped[str | None] = mapped_column(String(64))
    customer_name: Mapped[str | None] = mapped_column(String(100))
    customer_phone: Mapped[str | None] = mapped_column(String(20))
    customer_email: Mapped[str | None] = mapped_column(String(254))
    car_registration: Mapped[str | None] = mapped_column(String(8))
    car_make: Mapped[str | None] = mapped_column(String(50))
    car_model: Mapped[str | None] = mapped_column(String(50))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    reservation: Mapped[Reservation] = relationship()
    items: Mapped[list["BookingItem"]] = relationship(
        order_by="BookingItem.position",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class BookingItem(Base):
    """One service on a booking, with its name, price and duration as they were when booked."""

    __tablename__ = "booking_items"
    __table_args__ = (
        CheckConstraint("duration_minutes > 0", name="duration_positive"),
        CheckConstraint("price_from_pence >= 0", name="price_from_non_negative"),
        CheckConstraint(
            "price_to_pence IS NULL OR price_to_pence >= price_from_pence",
            name="price_range_ordered",
        ),
        UniqueConstraint("booking_id", "position", name="uq_booking_items_booking_id_position"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id", ondelete="CASCADE"))
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id"))
    service_name: Mapped[str] = mapped_column(String(100))
    price_from_pence: Mapped[int] = mapped_column(Integer)
    price_to_pence: Mapped[int | None] = mapped_column(Integer)
    duration_minutes: Mapped[int] = mapped_column(Integer)
    position: Mapped[int] = mapped_column(Integer)

    # Read for the slug only: the slug identifies a service, so it isn't snapshotted.
    service: Mapped[Service] = relationship(viewonly=True)
