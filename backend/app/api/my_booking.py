"""The customer's booking page: view and cancel a booking from the private link in an email.

The token comes in the body, never the URL, so it stays out of logs. Any bad link, however
mangled, gets the same 404.
"""

import logging
from datetime import datetime, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.holds import REFERENCE_LENGTH, BookingSummaryOut, booking_summary, local_iso
from app.bookings.rules import customer_can_cancel
from app.bookings.self_service import (
    CancelRefused,
    LinkNotValid,
    cancel_from_link,
    view_from_link,
)
from app.clock import utc_now
from app.db import get_session
from app.models import Booking
from app.payments.deps import get_payment_provider
from app.payments.provider import PaymentProvider, PaymentUnavailable
from app.repositories.availability import (
    SettingsUnavailable,
    load_free_cancellation_hours,
    load_policy,
)

router = APIRouter()
log = logging.getLogger("uvicorn.error")

SessionDep = Annotated[Session, Depends(get_session)]
NowDep = Annotated[datetime, Depends(utc_now)]
ProviderDep = Annotated[PaymentProvider, Depends(get_payment_provider)]

NOT_VALID = HTTPException(status_code=404, detail="This link isn't valid")


class LinkIn(BaseModel):
    # A plain str: an oversized token must reach the lookup and get 404, not 422.
    token: str


class MyBookingOut(BaseModel):
    summary: BookingSummaryOut
    deposit_status: str
    can_cancel: bool
    refund_if_cancelled: bool
    free_cancellation_until: str


def _check_reference(reference: str) -> None:
    if len(reference) > REFERENCE_LENGTH or "\x00" in reference:
        raise NOT_VALID


def _settings(session: Session) -> tuple[ZoneInfo, int]:
    try:
        return load_policy(session).zone, load_free_cancellation_hours(session)
    except SettingsUnavailable as error:
        raise HTTPException(status_code=503, detail="Booking unavailable") from error


def _out(
    session: Session, booking: Booking, now: datetime, zone: ZoneInfo, hours: int
) -> MyBookingOut:
    can_cancel = customer_can_cancel(booking.status, booking.start_at, now, hours)
    return MyBookingOut(
        summary=booking_summary(session, booking, zone),
        deposit_status=booking.deposit_status,
        can_cancel=can_cancel,
        refund_if_cancelled=can_cancel and booking.deposit_status == "paid",
        free_cancellation_until=local_iso(booking.start_at - timedelta(hours=hours), zone),
    )


@router.post("/bookings/{reference}/view")
def view(reference: str, body: LinkIn, session: SessionDep, now: NowDep) -> MyBookingOut:
    """The booking this link opens, and whether it can still be cancelled."""
    _check_reference(reference)
    zone, hours = _settings(session)
    try:
        booking = view_from_link(session, reference, body.token, now)
    except LinkNotValid as error:
        raise NOT_VALID from error
    return _out(session, booking, now, zone, hours)


@router.post("/bookings/{reference}/cancel")
def cancel(
    reference: str, body: LinkIn, session: SessionDep, now: NowDep, provider: ProviderDep
) -> MyBookingOut:
    """Cancel the booking, refunding its deposit. Only before the free-cancellation window."""
    _check_reference(reference)
    zone, hours = _settings(session)
    try:
        booking = cancel_from_link(session, provider, reference, body.token, now, hours)
    except LinkNotValid as error:
        session.rollback()
        raise NOT_VALID from error
    except CancelRefused as error:
        session.rollback()
        raise HTTPException(status_code=409, detail=error.reason) from error
    except PaymentUnavailable as error:
        session.rollback()  # nothing saved: still confirmed, still paid
        log.warning("cancel for %s: payment provider failed: %s", reference, error)
        raise HTTPException(status_code=503, detail="We couldn't cancel just now") from error
    session.commit()
    return _out(session, booking, now, zone, hours)
