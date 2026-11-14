"""The one interface every payment call goes through.

`StripeProvider` talks to Stripe, `DemoProvider` fakes a payment for a fresh clone with no
keys, and the tests use a fake. Nothing outside `app/payments` knows which one it has.
"""

from dataclasses import dataclass
from typing import Literal, Protocol

CheckoutStatus = Literal["open", "complete", "expired"]
RefundStatus = Literal["pending", "succeeded", "failed"]


@dataclass(frozen=True)
class CheckoutStarted:
    session_ref: str
    client_secret: str | None  # for Stripe's embedded form; None in demo mode


@dataclass(frozen=True)
class CheckoutState:
    status: CheckoutStatus
    paid: bool
    payment_intent_ref: str | None
    client_secret: str | None


@dataclass(frozen=True)
class RefundState:
    refund_ref: str
    status: RefundStatus


class PaymentUnavailable(Exception):
    """The provider couldn't be reached or refused the request. Nothing was decided."""


class PaymentProvider(Protocol):
    name: str  # "stripe" or "demo", stored on each payment row

    def start_checkout(
        self,
        *,
        reference: str,
        amount_pence: int,
        customer_email: str,
        description: str,
        idempotency_key: str,
    ) -> CheckoutStarted: ...

    def get_checkout(self, session_ref: str) -> CheckoutState: ...

    def close_checkout(self, session_ref: str) -> bool:
        """Close the payment form. False means it had already completed: a payment got in."""
        ...

    def refund(
        self, *, payment_intent_ref: str, amount_pence: int, idempotency_key: str
    ) -> RefundState: ...

    def get_refund(self, refund_ref: str) -> RefundState: ...
