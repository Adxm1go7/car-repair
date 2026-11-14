"""Holding a slot, moving it on to payment, and releasing it.

Routes call these; they call the repositories.

Nothing here commits: the caller decides when the work is done.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.bookings.rules import hash_token, new_hold_token, new_reference, token_matches
from app.models import Booking, BookingItem, Payment, Service
from app.payments.provider import PaymentProvider, PaymentUnavailable
from app.payments.service import close_open_deposit, complete_deposit
from app.repositories.bookings import (
    get_booking_for_update,
    hold_has_expired,
    release_expired_holds,
    release_hold,
)
from app.repositories.payments import count_payments, get_open_deposit
from app.repositories.reservations import reserve

log = logging.getLogger("app.bookings")

REFERENCE_ATTEMPTS = 3
REFERENCE_CONSTRAINT = "uq_bookings_reference"


@dataclass(frozen=True)
class HoldCreated:
    booking: Booking
    token: str  # the only time the plain token exists; the database keeps its hash


def create_hold(
    session: Session,
    services: Sequence[Service],
    start: datetime,
    now: datetime,
    hold_minutes: int,
) -> HoldCreated:
    """Reserve `start` for these services and record a held booking. Raises SlotUnavailable.

    Expired holds are released first: their reservations are still active until something
    flips them, and the overlap constraint would otherwise refuse the new one.
    """
    release_expired_holds(session, now)
    reserved = reserve(session, [service.id for service in services], start, now)

    token = new_hold_token()
    for attempt in range(REFERENCE_ATTEMPTS):
        items = [
            BookingItem(
                service_id=service.id,
                service_name=service.name,
                price_from_pence=service.price_from_pence,
                price_to_pence=service.price_to_pence,
                duration_minutes=service.duration_minutes,
                position=position,
            )
            for position, service in enumerate(services)
        ]
        booking = Booking(
            reference=new_reference(),
            reservation=reserved.reservation,
            status="held",
            start_at=reserved.start,
            end_at=reserved.end,
            hold_expires_at=now + timedelta(minutes=hold_minutes),
            hold_token_hash=hash_token(token),
            items=items,
        )
        try:
            with session.begin_nested():
                session.add(booking)
                session.flush()
        except IntegrityError as error:
            constraint = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
            if constraint != REFERENCE_CONSTRAINT or attempt == REFERENCE_ATTEMPTS - 1:
                raise
            continue  # the reference is taken (very rare): try another
        return HoldCreated(booking=booking, token=token)
    raise AssertionError("unreachable")  # pragma: no cover


class HoldNotFound(Exception):
    """No such booking, or the token doesn't match. Callers can't tell which, by design."""


class HoldExpired(Exception):
    """The hold ran out. The caller must commit, so the release it made is kept."""


class AlreadyConfirmed(Exception):
    """The booking is confirmed (paid), so a hold action can't change it."""


@dataclass(frozen=True)
class CustomerDetails:
    """Already cleaned by the `clean_*` rules."""

    name: str
    phone: str
    email: str
    registration: str
    make: str
    model: str
    notes: str | None


def _locked(session: Session, reference: str, token: str) -> Booking:
    booking = get_booking_for_update(session, reference)
    if booking is None or not token_matches(token, booking.hold_token_hash):
        raise HoldNotFound
    return booking


def _seconds_left(booking: Booking, now: datetime) -> int:
    expires = booking.hold_expires_at or now
    return max(0, int((expires - now).total_seconds()))


def _close_quietly(
    session: Session, provider: PaymentProvider, booking: Booking, now: datetime
) -> Booking | None:
    """Close the booking's open payment form, best effort. The worker retries a failed close.
    Returns the booking when a payment had got in and confirmed it."""
    try:
        return close_open_deposit(session, provider, booking, now)
    except PaymentUnavailable:
        log.warning("couldn't close the payment form for %s; the worker will", booking.reference)
        return None


@dataclass(frozen=True)
class CheckoutResult:
    client_secret: str | None  # for Stripe's embedded form
    demo_session: str | None  # for the demo pay buttons
    expires_in_seconds: int
    amount_pence: int


def start_checkout(
    session: Session,
    provider: PaymentProvider,
    reference: str,
    token: str,
    details: CustomerDetails,
    now: datetime,
    *,
    payment_hold_minutes: int,
    amount_pence: int,
    zone: ZoneInfo,
) -> CheckoutResult:
    """Save the details, restart the hold for payment, and open the deposit's payment form.

    A repeat call while the form is open returns the same form, with the time left, and
    changes nothing. PaymentUnavailable propagates: the caller must roll back.
    """
    booking = _locked(session, reference, token)
    if booking.status == "confirmed":
        raise AlreadyConfirmed
    if hold_has_expired(booking, now):
        release_hold(session, booking)
        if _close_quietly(session, provider, booking, now) is not None:
            raise AlreadyConfirmed
        raise HoldExpired
    if booking.status != "held":
        raise HoldExpired

    open_deposit = get_open_deposit(session, booking.id)
    if open_deposit is not None:
        state = provider.get_checkout(open_deposit.provider_ref)
        return CheckoutResult(
            client_secret=state.client_secret,
            demo_session=open_deposit.provider_ref if provider.name == "demo" else None,
            expires_in_seconds=_seconds_left(booking, now),
            amount_pence=open_deposit.amount_pence,
        )

    booking.customer_name = details.name
    booking.customer_phone = details.phone
    booking.customer_email = details.email
    booking.car_registration = details.registration
    booking.car_make = details.make
    booking.car_model = details.model
    booking.notes = details.notes
    booking.hold_expires_at = now + timedelta(minutes=payment_hold_minutes)
    when = booking.start_at.astimezone(zone).strftime("%a %d %b %H:%M")
    attempt = count_payments(session, booking_id=booking.id)
    started = provider.start_checkout(
        reference=booking.reference,
        amount_pence=amount_pence,
        customer_email=details.email,
        description=f"Deposit for booking {booking.reference}, {when}",
        # Stripe remembers keys per account for 24 hours, so they must be unique across every
        # database that shares the account: the random reference is, a row id isn't.
        idempotency_key=f"deposit-{booking.reference}-{attempt}",
    )
    session.add(
        Payment(
            booking_id=booking.id,
            kind="deposit",
            provider=provider.name,
            provider_ref=started.session_ref,
            amount_pence=amount_pence,
            status="open",
        )
    )
    session.flush()
    return CheckoutResult(
        client_secret=started.client_secret,
        demo_session=started.session_ref if provider.name == "demo" else None,
        expires_in_seconds=payment_hold_minutes * 60,
        amount_pence=amount_pence,
    )


def hold_status(
    session: Session, provider: PaymentProvider, reference: str, token: str, now: datetime
) -> Booking:
    """Where the booking stands. A payment the provider already has is completed first, so
    the page doesn't depend on the webhook arriving; a hold past its time is released."""
    booking = _locked(session, reference, token)
    open_deposit = get_open_deposit(session, booking.id)
    if open_deposit is not None and booking.status in ("held", "expired"):
        try:
            complete_deposit(session, provider, open_deposit.provider_ref, now)
        except PaymentUnavailable:
            log.warning("couldn't ask the provider about %s; still waiting", booking.reference)
    if hold_has_expired(booking, now):
        release_hold(session, booking)
        _close_quietly(session, provider, booking, now)
    return booking


def cancel_hold(
    session: Session, provider: PaymentProvider, reference: str, token: str, now: datetime
) -> None:
    """Give a held slot back and close its payment form. Releasing one already expired is
    fine. If a payment got in before the form closed, the booking is confirmed instead and
    AlreadyConfirmed tells the caller (who must still commit)."""
    booking = _locked(session, reference, token)
    if booking.status not in ("held", "expired"):
        raise AlreadyConfirmed
    if _close_quietly(session, provider, booking, now) is not None:
        raise AlreadyConfirmed
    if booking.status == "held":
        release_hold(session, booking)


def summary_services(booking: Booking) -> list[dict[str, object]]:
    """The services on a booking, from the snapshots taken when it was made."""
    return [
        {
            "slug": item.service.slug,
            "name": item.service_name,
            "duration_minutes": item.duration_minutes,
            "price_from_pence": item.price_from_pence,
            "price_to_pence": item.price_to_pence,
        }
        for item in booking.items
    ]
