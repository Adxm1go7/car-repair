"""Payments and provider events in the database."""

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import Booking, Payment, PaymentEvent


def get_payment_for_update(session: Session, provider: str, ref: str) -> Payment | None:
    """The payment with this provider reference, locked until the transaction ends."""
    return session.scalars(
        select(Payment)
        .where(Payment.provider == provider, Payment.provider_ref == ref)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one_or_none()


def find_payment(session: Session, provider: str, ref: str) -> Payment | None:
    return session.scalars(
        select(Payment).where(Payment.provider == provider, Payment.provider_ref == ref)
    ).one_or_none()


def get_open_deposit(session: Session, booking_id: int) -> Payment | None:
    return session.scalars(
        select(Payment).where(
            Payment.booking_id == booking_id, Payment.kind == "deposit", Payment.status == "open"
        )
    ).one_or_none()


def paid_deposit(session: Session, booking_id: int) -> Payment | None:
    return session.scalars(
        select(Payment).where(
            Payment.booking_id == booking_id, Payment.kind == "deposit", Payment.status == "paid"
        )
    ).one_or_none()


def count_payments(
    session: Session, *, booking_id: int | None = None, refund_of: int | None = None
) -> int:
    """Deposit rows for a booking, or refund rows for a deposit: the next idempotency key."""
    statement = select(func.count()).select_from(Payment)
    if booking_id is not None:
        statement = statement.where(Payment.booking_id == booking_id, Payment.kind == "deposit")
    if refund_of is not None:
        statement = statement.where(Payment.refund_of == refund_of)
    return session.scalar(statement) or 0


def record_event(session: Session, provider: str, event_id: str, type: str) -> bool:
    """Remember an event. False if it was already there, so the caller does nothing twice."""
    inserted = session.scalar(
        insert(PaymentEvent)
        .values(provider=provider, event_id=event_id, type=type)
        .on_conflict_do_nothing(index_elements=["provider", "event_id"])
        .returning(PaymentEvent.event_id)
    )
    return inserted is not None


def stale_open_deposits(session: Session) -> list[Payment]:
    """Payment forms still open for bookings that are no longer held: close them."""
    return list(
        session.scalars(
            select(Payment)
            .join(Booking, Booking.id == Payment.booking_id)
            .where(Payment.kind == "deposit", Payment.status == "open", Booking.status != "held")
            .order_by(Payment.id)
        )
    )
