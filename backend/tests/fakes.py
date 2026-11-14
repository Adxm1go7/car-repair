"""A payment provider for tests: records every call, and can be told what Stripe would say."""

from dataclasses import dataclass, field

from app.payments.provider import (
    CheckoutStarted,
    CheckoutState,
    PaymentUnavailable,
    RefundState,
    RefundStatus,
)


@dataclass
class FakeProvider:
    name: str = "stripe"
    paid: set[str] = field(default_factory=set)
    closed: set[str] = field(default_factory=set)
    refund_status: RefundStatus = "pending"
    fail: bool = False  # every call raises PaymentUnavailable while True
    fail_calls: set[str] = field(default_factory=set)  # only these calls fail
    calls: list[tuple[str, dict[str, object]]] = field(default_factory=list)
    refunds: dict[str, RefundStatus] = field(default_factory=dict)
    _sessions: int = 0

    def _call(self, name: str, **args: object) -> None:
        self.calls.append((name, args))
        if self.fail or name in self.fail_calls:
            raise PaymentUnavailable("fake provider told to fail")

    def called(self, name: str) -> list[dict[str, object]]:
        return [args for call, args in self.calls if call == name]

    def mark_paid(self, session_ref: str) -> None:
        self.paid.add(session_ref)

    def start_checkout(
        self,
        *,
        reference: str,
        amount_pence: int,
        customer_email: str,
        description: str,
        idempotency_key: str,
    ) -> CheckoutStarted:
        self._call(
            "start_checkout",
            reference=reference,
            amount_pence=amount_pence,
            customer_email=customer_email,
            description=description,
            idempotency_key=idempotency_key,
        )
        self._sessions += 1
        ref = f"cs_fake_{self._sessions}"
        return CheckoutStarted(ref, f"{ref}_secret")

    def get_checkout(self, session_ref: str) -> CheckoutState:
        self._call("get_checkout", session_ref=session_ref)
        if session_ref in self.paid:
            return CheckoutState("complete", True, f"pi_{session_ref}", None)
        if session_ref in self.closed:
            return CheckoutState("expired", False, None, None)
        return CheckoutState("open", False, None, f"{session_ref}_secret")

    def close_checkout(self, session_ref: str) -> bool:
        self._call("close_checkout", session_ref=session_ref)
        if session_ref in self.paid:
            return False
        self.closed.add(session_ref)
        return True

    def refund(
        self, *, payment_intent_ref: str, amount_pence: int, idempotency_key: str
    ) -> RefundState:
        self._call(
            "refund",
            payment_intent_ref=payment_intent_ref,
            amount_pence=amount_pence,
            idempotency_key=idempotency_key,
        )
        ref = f"re_fake_{len(self.refunds) + 1}"
        self.refunds[ref] = self.refund_status
        return RefundState(ref, self.refund_status)

    def get_refund(self, refund_ref: str) -> RefundState:
        self._call("get_refund", refund_ref=refund_ref)
        return RefundState(refund_ref, self.refunds.get(refund_ref, self.refund_status))
