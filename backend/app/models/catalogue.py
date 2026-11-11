"""What the garage sells, where the work happens, and when it is open."""

from datetime import time

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String, Text, Time, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class BayType(Base):
    __tablename__ = "bay_types"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(100))


class Bay(Base):
    __tablename__ = "bays"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    bay_type_id: Mapped[int] = mapped_column(ForeignKey("bay_types.id"))
    active: Mapped[bool] = mapped_column(Boolean, server_default=true())

    bay_type: Mapped[BayType] = relationship()


class Service(Base):
    __tablename__ = "services"
    __table_args__ = (
        CheckConstraint("duration_minutes > 0", name="duration_positive"),
        CheckConstraint("price_from_pence >= 0", name="price_from_non_negative"),
        CheckConstraint(
            "price_to_pence IS NULL OR price_to_pence >= price_from_pence",
            name="price_range_ordered",
        ),
        CheckConstraint(
            "approval_mode IN ('instant', 'needs_approval')", name="approval_mode_valid"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    category: Mapped[str] = mapped_column(String(50))
    description: Mapped[str] = mapped_column(Text)
    duration_minutes: Mapped[int] = mapped_column(Integer)
    price_from_pence: Mapped[int] = mapped_column(Integer)
    price_to_pence: Mapped[int | None] = mapped_column(Integer)
    required_bay_type_id: Mapped[int] = mapped_column(ForeignKey("bay_types.id"))
    approval_mode: Mapped[str] = mapped_column(String(20))
    active: Mapped[bool] = mapped_column(Boolean, server_default=true())
    sort_order: Mapped[int] = mapped_column(Integer)

    required_bay_type: Mapped[BayType] = relationship()


class OpeningHours(Base):
    """One row per weekday (0 = Monday). Times are garage-local wall-clock times."""

    __tablename__ = "opening_hours"
    __table_args__ = (
        CheckConstraint("weekday BETWEEN 0 AND 6", name="weekday_range"),
        CheckConstraint("(open_time IS NULL) = (close_time IS NULL)", name="open_close_together"),
        CheckConstraint("open_time < close_time", name="open_before_close"),
    )

    weekday: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    open_time: Mapped[time | None] = mapped_column(Time)
    close_time: Mapped[time | None] = mapped_column(Time)

    breaks: Mapped[list["OpeningHoursBreak"]] = relationship(
        order_by="OpeningHoursBreak.start_time",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class OpeningHoursBreak(Base):
    __tablename__ = "opening_hours_breaks"
    __table_args__ = (CheckConstraint("start_time < end_time", name="start_before_end"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    weekday: Mapped[int] = mapped_column(ForeignKey("opening_hours.weekday", ondelete="CASCADE"))
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)
