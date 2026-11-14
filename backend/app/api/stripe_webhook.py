"""Stripe's messages about payments and refunds.

Each event is checked against `STRIPE_WEBHOOK_SECRET` on the raw body, recorded by id in the
same transaction as its handling (so a repeat does nothing and a failure is retried by
Stripe), and acted on only after re-reading the state from Stripe.
"""

import json
import logging
from datetime import datetime
from typing import Annotated, Any

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.clock import utc_now
from app.config import AppConfig
from app.db import get_session
from app.payments.deps import get_payment_provider
from app.payments.provider import PaymentProvider, PaymentUnavailable
from app.payments.service import apply_refund_update, complete_deposit, expire_open_deposit
from app.repositories.payments import record_event

router = APIRouter()
log = logging.getLogger("app.webhook")

SessionDep = Annotated[Session, Depends(get_session)]
NowDep = Annotated[datetime, Depends(utc_now)]
ProviderDep = Annotated[PaymentProvider, Depends(get_payment_provider)]

COMPLETED = {"checkout.session.completed", "checkout.session.async_payment_succeeded"}
EXPIRED = {"checkout.session.expired"}
REFUNDED = {"refund.updated", "refund.created", "charge.refund.updated"}
TOLERANCE_SECONDS = 300  # older signed timestamps are refused, so a captured event can't replay


class RefundNotStoredYet(Exception):
    """A refund event arrived before our transaction that created the refund committed."""


def _handle(
    session: Session, provider: PaymentProvider, kind: str, object_id: str, now: datetime
) -> None:
    if kind in COMPLETED:
        complete_deposit(session, provider, object_id, now)
    elif kind in EXPIRED:
        expire_open_deposit(session, provider.name, object_id)
    elif kind in REFUNDED and not apply_refund_update(session, provider, object_id):
        raise RefundNotStoredYet


@router.post("/stripe/webhook")
async def stripe_webhook(
    request: Request, session: SessionDep, provider: ProviderDep, now: NowDep
) -> Response:
    config: AppConfig = request.app.state.config
    if not config.stripe_webhook_secret:
        raise HTTPException(status_code=503, detail="Webhooks are not configured")
    payload = await request.body()
    try:
        stripe.WebhookSignature.verify_header(
            payload,
            request.headers.get("Stripe-Signature"),
            config.stripe_webhook_secret,
            TOLERANCE_SECONDS,
        )
    except stripe.SignatureVerificationError as error:
        raise HTTPException(status_code=400, detail="Invalid signature") from error

    try:
        body: dict[str, Any] = json.loads(payload)
        event_id = str(body["id"])
        kind = str(body["type"])
        object_id = str(body["data"]["object"]["id"])
    except (ValueError, KeyError, TypeError) as error:
        raise HTTPException(status_code=400, detail="Invalid event") from error

    if not record_event(session, "stripe", event_id, kind):
        log.info("event %s (%s) already handled", event_id, kind)
        return Response(status_code=200)
    try:
        _handle(session, provider, kind, object_id, now)
    except RefundNotStoredYet:
        session.rollback()  # not recorded, so Stripe's retry is handled
        log.info(
            "event %s for refund %s not stored yet; asking Stripe to retry", event_id, object_id
        )
        return Response(status_code=503)
    except PaymentUnavailable:
        session.rollback()
        log.warning("event %s (%s) failed on the provider; Stripe will retry", event_id, kind)
        return Response(status_code=500)
    session.commit()
    log.info("event %s (%s) handled", event_id, kind)
    return Response(status_code=200)
