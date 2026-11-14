"""Which payment provider a request or the worker gets."""

from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.config import AppConfig
from app.db import get_session
from app.payments.demo_provider import DemoProvider
from app.payments.provider import PaymentProvider
from app.payments.stripe_provider import StripeProvider


def make_provider(config: AppConfig, session: Session) -> PaymentProvider:
    """Stripe when a secret key is configured, otherwise demo payments."""
    if config.payment_provider == "stripe":
        return StripeProvider(config.stripe_secret_key)
    return DemoProvider(session)


def get_payment_provider(
    request: Request, session: Annotated[Session, Depends(get_session)]
) -> PaymentProvider:
    stripe_provider: PaymentProvider | None = request.app.state.stripe_provider
    return stripe_provider if stripe_provider is not None else DemoProvider(session)
