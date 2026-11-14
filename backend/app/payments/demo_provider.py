"""Demo payments, for a fresh clone with no Stripe keys. Never used in production or CI.

There is no outside service: a demo "session" is just the deposit's `payments` row, and it
counts as paid once its `payment_intent_ref` is set (by the demo pay endpoint).
"""

import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Payment
from app.payments.provider import CheckoutStarted, CheckoutState, RefundState


class DemoProvider:
    name = "demo"

    def __init__(self, session: Session) -> None:
        self._session = session

    def _deposit(self, session_ref: str) -> Payment | None:
        return self._session.scalars(
            select(Payment).where(
                Payment.provider == self.name,
                Payment.provider_ref == session_ref,
                Payment.kind == "deposit",
            )
        ).one_or_none()

    def start_checkout(
        self,
        *,
        reference: str,
        amount_pence: int,
        customer_email: str,
        description: str,
        idempotency_key: str,
    ) -> CheckoutStarted:
        return CheckoutStarted(f"demo_{secrets.token_urlsafe(16)}", None)

    def mark_paid(self, session_ref: str) -> None:
        """What paying does in demo mode. The caller then runs `complete_deposit`."""
        deposit = self._deposit(session_ref)
        if deposit is not None and deposit.payment_intent_ref is None:
            deposit.payment_intent_ref = f"demo_pi_{secrets.token_urlsafe(12)}"
            self._session.flush()

    def get_checkout(self, session_ref: str) -> CheckoutState:
        deposit = self._deposit(session_ref)
        if deposit is None or deposit.status == "expired":
            return CheckoutState("expired", False, None, None)
        if deposit.payment_intent_ref is not None:
            return CheckoutState("complete", True, deposit.payment_intent_ref, None)
        return CheckoutState("open", False, None, None)

    def close_checkout(self, session_ref: str) -> bool:
        return not self.get_checkout(session_ref).paid

    def refund(
        self, *, payment_intent_ref: str, amount_pence: int, idempotency_key: str
    ) -> RefundState:
        return RefundState(f"demo_re_{secrets.token_urlsafe(12)}", "succeeded")

    def get_refund(self, refund_ref: str) -> RefundState:
        return RefundState(refund_ref, "succeeded")
