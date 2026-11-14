"""Payments through Stripe (Embedded Checkout). The only module that calls Stripe's API."""

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

import stripe
from stripe.params.checkout import SessionCreateParams

from app.clock import utc_now
from app.payments.provider import (
    CheckoutStarted,
    CheckoutState,
    CheckoutStatus,
    PaymentUnavailable,
    RefundState,
    RefundStatus,
)

# Pinned, so a change to the account's default API version can't change behaviour.
STRIPE_API_VERSION = "2026-10-28.endive"
TIMEOUT_SECONDS = 10
# Stripe's minimum lifetime for a Checkout Session is 30 minutes; our hold ends sooner and
# closes it early (payment_hold_minutes is at most 25).
SESSION_LIFETIME = timedelta(minutes=31)

_REFUND_STATUSES: dict[str, RefundStatus] = {
    "succeeded": "succeeded",
    "failed": "failed",
    "canceled": "failed",
}


def _checkout_status(value: object) -> CheckoutStatus:
    if value == "complete":
        return "complete"
    if value == "expired":
        return "expired"
    return "open"


class StripeProvider:
    name = "stripe"

    def __init__(
        self,
        secret_key: str,
        *,
        client: Any = None,
        now: Callable[[], datetime] = utc_now,
    ) -> None:
        # The key lives only inside the client, so it isn't in this object's repr or vars.
        self._client = client or stripe.StripeClient(
            secret_key,
            stripe_version=STRIPE_API_VERSION,
            max_network_retries=2,
            http_client=stripe.new_default_http_client(timeout=TIMEOUT_SECONDS),
        )
        self._now = now

    def __repr__(self) -> str:
        return "StripeProvider()"

    def start_checkout(
        self,
        *,
        reference: str,
        amount_pence: int,
        customer_email: str,
        description: str,
        idempotency_key: str,
    ) -> CheckoutStarted:
        params: SessionCreateParams = {
            "ui_mode": "embedded_page",
            "redirect_on_completion": "never",  # the page asks our server instead
            "mode": "payment",
            "allowed_payment_method_types": ["card"],  # cards only: no redirect-based methods
            "line_items": [
                {
                    "quantity": 1,
                    "price_data": {
                        "currency": "gbp",
                        "unit_amount": amount_pence,
                        "product_data": {"name": description},
                    },
                }
            ],
            "customer_email": customer_email,
            "client_reference_id": reference,
            "metadata": {"reference": reference},
            "expires_at": int((self._now() + SESSION_LIFETIME).timestamp()),
        }
        try:
            session = self._client.v1.checkout.sessions.create(
                params=params, options={"idempotency_key": idempotency_key}
            )
        except stripe.StripeError as error:
            raise PaymentUnavailable(type(error).__name__) from error
        return CheckoutStarted(session_ref=session.id, client_secret=session.client_secret)

    def get_checkout(self, session_ref: str) -> CheckoutState:
        try:
            session = self._client.v1.checkout.sessions.retrieve(session_ref)
        except stripe.StripeError as error:
            raise PaymentUnavailable(type(error).__name__) from error
        intent = session.payment_intent
        return CheckoutState(
            status=_checkout_status(session.status),
            paid=session.payment_status == "paid",
            payment_intent_ref=intent if isinstance(intent, str) or intent is None else intent.id,
            client_secret=session.client_secret,
        )

    def close_checkout(self, session_ref: str) -> bool:
        try:
            self._client.v1.checkout.sessions.expire(session_ref)
            return True
        except stripe.InvalidRequestError:
            # It isn't open any more: either it already expired, or the customer paid.
            return self.get_checkout(session_ref).status != "complete"
        except stripe.StripeError as error:
            raise PaymentUnavailable(type(error).__name__) from error

    def refund(
        self, *, payment_intent_ref: str, amount_pence: int, idempotency_key: str
    ) -> RefundState:
        try:
            refund = self._client.v1.refunds.create(
                params={"payment_intent": payment_intent_ref, "amount": amount_pence},
                options={"idempotency_key": idempotency_key},
            )
        except stripe.StripeError as error:
            raise PaymentUnavailable(type(error).__name__) from error
        return RefundState(refund.id, _REFUND_STATUSES.get(refund.status or "", "pending"))

    def get_refund(self, refund_ref: str) -> RefundState:
        try:
            refund = self._client.v1.refunds.retrieve(refund_ref)
        except stripe.StripeError as error:
            raise PaymentUnavailable(type(error).__name__) from error
        return RefundState(refund.id, _REFUND_STATUSES.get(refund.status or "", "pending"))
