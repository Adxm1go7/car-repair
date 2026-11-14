"""Money in and out: each deposit attempt and each refund, and the provider events seen.

A deposit's `provider_ref` is the checkout session (Stripe's `cs_…`); a refund's is the
refund (`re_…`). The partial unique indexes make a second open deposit, or a second live
refund of one deposit, impossible whatever the code does.
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
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.booking import Booking

PAYMENT_KINDS: Final[tuple[str, ...]] = ("deposit", "refund")
DEPOSIT_PAYMENT_STATUSES: Final[tuple[str, ...]] = ("open", "paid", "expired")
REFUND_STATUSES: Final[tuple[str, ...]] = ("pending", "succeeded", "failed")


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


STATUS_SUITS_KIND = (
    f"(kind = 'deposit' AND refund_of IS NULL AND status IN ({_quoted(DEPOSIT_PAYMENT_STATUSES)}))"
    f" OR (kind = 'refund' AND refund_of IS NOT NULL AND status IN ({_quoted(REFUND_STATUSES)}))"
)


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint(f"kind IN ({_quoted(PAYMENT_KINDS)})", name="kind_valid"),
        CheckConstraint(STATUS_SUITS_KIND, name="status_suits_kind"),
        CheckConstraint("amount_pence > 0", name="amount_positive"),
        UniqueConstraint("provider", "provider_ref", name="uq_payments_provider_provider_ref"),
        Index(
            "ux_payments_one_open_deposit",
            "booking_id",
            unique=True,
            postgresql_where=text("kind = 'deposit' AND status = 'open'"),
        ),
        Index(
            "ux_payments_one_live_refund",
            "refund_of",
            unique=True,
            postgresql_where=text("kind = 'refund' AND status <> 'failed'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id"))
    kind: Mapped[str] = mapped_column(String(10))
    provider: Mapped[str] = mapped_column(String(10))
    provider_ref: Mapped[str] = mapped_column(String(255))
    payment_intent_ref: Mapped[str | None] = mapped_column(String(255))
    amount_pence: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), server_default="gbp")
    status: Mapped[str] = mapped_column(String(10))
    refund_of: Mapped[int | None] = mapped_column(ForeignKey("payments.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    booking: Mapped[Booking] = relationship()


class PaymentEvent(Base):
    """A provider event already handled. Only its id and type: the payload holds personal data."""

    __tablename__ = "payment_events"

    provider: Mapped[str] = mapped_column(String(10), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    type: Mapped[str] = mapped_column(String(100))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
