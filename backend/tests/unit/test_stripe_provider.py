"""StripeProvider sends exactly what the design asks for. No network: the client is a mock."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
import stripe

from app.payments.provider import PaymentUnavailable
from app.payments.stripe_provider import StripeProvider

NOW = datetime(2026, 11, 9, 9, tzinfo=UTC)
SECRET = "sk_test_do_not_print"  # noqa: S105 - not a real key
CLIENT_SECRET = "cs_1_secret"  # noqa: S105 - not a real secret


def invalid_request(message: str) -> stripe.InvalidRequestError:
    return stripe.InvalidRequestError(message, param=None)  # type: ignore[no-untyped-call]


def connection_error() -> stripe.APIConnectionError:
    return stripe.APIConnectionError("down")  # type: ignore[no-untyped-call]


def provider() -> tuple[StripeProvider, MagicMock]:
    client = MagicMock()
    return StripeProvider(SECRET, client=client, now=lambda: NOW), client


def start(p: StripeProvider) -> None:
    p.start_checkout(
        reference="7K3Q-M2PX",
        amount_pence=2000,
        customer_email="sam@example.com",
        description="Deposit for booking 7K3Q-M2PX",
        idempotency_key="deposit-1-0",
    )


def test_start_checkout_sends_the_design_parameters() -> None:
    p, client = provider()
    client.v1.checkout.sessions.create.return_value = MagicMock(
        id="cs_1", client_secret=CLIENT_SECRET
    )
    start(p)
    params = client.v1.checkout.sessions.create.call_args.kwargs["params"]
    options = client.v1.checkout.sessions.create.call_args.kwargs["options"]
    assert params["ui_mode"] == "embedded_page"
    assert params["redirect_on_completion"] == "never"
    assert params["mode"] == "payment"
    assert params["allowed_payment_method_types"] == ["card"]
    assert params["customer_email"] == "sam@example.com"
    assert params["client_reference_id"] == "7K3Q-M2PX"
    assert params["metadata"] == {"reference": "7K3Q-M2PX"}
    assert params["expires_at"] == int((NOW + timedelta(minutes=31)).timestamp())
    (item,) = params["line_items"]
    assert item["quantity"] == 1
    assert item["price_data"]["currency"] == "gbp"
    assert item["price_data"]["unit_amount"] == 2000
    assert item["price_data"]["product_data"]["name"] == "Deposit for booking 7K3Q-M2PX"
    assert options == {"idempotency_key": "deposit-1-0"}


def test_start_checkout_returns_session_and_secret() -> None:
    p, client = provider()
    client.v1.checkout.sessions.create.return_value = MagicMock(
        id="cs_1", client_secret=CLIENT_SECRET
    )
    result = p.start_checkout(
        reference="R",
        amount_pence=2000,
        customer_email="e@x.io",
        description="d",
        idempotency_key="k",
    )
    assert (result.session_ref, result.client_secret) == ("cs_1", CLIENT_SECRET)


def test_get_checkout_reads_paid_state() -> None:
    p, client = provider()
    client.v1.checkout.sessions.retrieve.return_value = MagicMock(
        status="complete", payment_status="paid", payment_intent="pi_1", client_secret=CLIENT_SECRET
    )
    state = p.get_checkout("cs_1")
    assert (state.status, state.paid, state.payment_intent_ref) == ("complete", True, "pi_1")


def test_refund_sends_payment_intent_amount_and_key() -> None:
    p, client = provider()
    client.v1.refunds.create.return_value = MagicMock(id="re_1", status="pending")
    result = p.refund(payment_intent_ref="pi_1", amount_pence=2000, idempotency_key="refund-3-0")
    client.v1.refunds.create.assert_called_once_with(
        params={"payment_intent": "pi_1", "amount": 2000},
        options={"idempotency_key": "refund-3-0"},
    )
    assert (result.refund_ref, result.status) == ("re_1", "pending")


@pytest.mark.parametrize(
    ("stripe_status", "ours"),
    [
        ("succeeded", "succeeded"),
        ("failed", "failed"),
        ("canceled", "failed"),
        ("requires_action", "pending"),
        ("pending", "pending"),
    ],
)
def test_refund_status_is_mapped(stripe_status: str, ours: str) -> None:
    p, client = provider()
    client.v1.refunds.retrieve.return_value = MagicMock(id="re_1", status=stripe_status)
    assert p.get_refund("re_1").status == ours


def test_close_open_session_returns_true() -> None:
    p, client = provider()
    assert p.close_checkout("cs_1") is True
    client.v1.checkout.sessions.expire.assert_called_once_with("cs_1")


def test_close_reports_completed_session_as_false() -> None:
    p, client = provider()
    client.v1.checkout.sessions.expire.side_effect = invalid_request(
        'Only Checkout Sessions with a status in ["open"] can be expired.'
    )
    client.v1.checkout.sessions.retrieve.return_value = MagicMock(
        status="complete", payment_status="paid", payment_intent="pi_1", client_secret=None
    )
    assert p.close_checkout("cs_1") is False


def test_close_already_expired_session_returns_true() -> None:
    p, client = provider()
    client.v1.checkout.sessions.expire.side_effect = invalid_request("x")
    client.v1.checkout.sessions.retrieve.return_value = MagicMock(
        status="expired", payment_status="unpaid", payment_intent=None, client_secret=None
    )
    assert p.close_checkout("cs_1") is True


def test_stripe_errors_become_payment_unavailable() -> None:
    p, client = provider()
    client.v1.checkout.sessions.create.side_effect = connection_error()
    with pytest.raises(PaymentUnavailable):
        start(p)
    client.v1.refunds.retrieve.side_effect = stripe.AuthenticationError("bad key")
    with pytest.raises(PaymentUnavailable):
        p.get_refund("re_1")


def test_secret_key_is_not_in_the_repr() -> None:
    p, _ = provider()
    assert SECRET not in repr(p)
    assert SECRET not in str(vars(p))


def test_unavailable_reason_names_the_error_and_code_but_not_the_message() -> None:
    p, client = provider()
    error = stripe.AuthenticationError(
        f"Invalid API Key provided: {SECRET[:8]}****", code="api_key_invalid"
    )
    client.v1.checkout.sessions.create.side_effect = error
    with pytest.raises(PaymentUnavailable) as raised:
        start(p)
    assert str(raised.value) == "AuthenticationError code=api_key_invalid"
