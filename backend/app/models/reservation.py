"""Time a bay is occupied, by a booking or a staff block. The database refuses overlaps."""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    func,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import TSTZRANGE, ExcludeConstraint, Range
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.catalogue import Bay


class Reservation(Base):
    """`during` is the occupied UTC range, half-open [start, end).

    For a booking it runs from the start to the real end plus the bay buffer.
    """

    __tablename__ = "reservations"
    __table_args__ = (
        CheckConstraint("kind IN ('booking', 'block')", name="kind_valid"),
        CheckConstraint(
            "NOT isempty(during) AND NOT lower_inf(during) AND NOT upper_inf(during)",
            name="during_bounded",
        ),
        ExcludeConstraint(
            ("bay_id", "="),
            ("during", "&&"),
            using="gist",
            where=text("active"),
            name="ex_reservations_no_overlap",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    bay_id: Mapped[int] = mapped_column(ForeignKey("bays.id"))
    kind: Mapped[str] = mapped_column(String(20))
    during: Mapped[Range[datetime]] = mapped_column(TSTZRANGE)
    active: Mapped[bool] = mapped_column(Boolean, server_default=true())
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    bay: Mapped[Bay] = relationship()
