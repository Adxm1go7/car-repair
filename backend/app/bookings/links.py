"""Booking links: the private token in an email that opens one booking.

Only the token's hash is stored, and a lookup is by that hash, so a database leak gives no
working links. A link works until a week after its booking ends.
"""

from datetime import datetime, timedelta
from typing import Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.bookings.rules import hash_token, new_hold_token
from app.models import Booking, BookingLink
from app.repositories.bookings import get_booking_for_update_by_id

LINK_VALID_AFTER_END: Final = timedelta(days=7)
# A real token is 43 characters. Anything much longer isn't one, so don't bother hashing it.
MAX_TOKEN_LENGTH: Final = 100


def create_link(session: Session, booking: Booking) -> str:
    """Add a new link for this booking and return its plain token. Flushes, doesn't commit."""
    token = new_hold_token()
    session.add(
        BookingLink(
            booking=booking,
            token_hash=hash_token(token),
            expires_at=booking.end_at + LINK_VALID_AFTER_END,
        )
    )
    session.flush()
    return token


def find_linked_booking(
    session: Session, reference: str, token: str, now: datetime, *, lock: bool = False
) -> Booking | None:
    """The booking this link opens, or None if the link is unknown, expired or for another
    booking. With lock=True the booking row is locked for update."""
    if len(token) > MAX_TOKEN_LENGTH:
        return None
    link = session.scalars(
        select(BookingLink).where(BookingLink.token_hash == hash_token(token))
    ).one_or_none()
    if link is None or link.expires_at <= now:
        return None
    booking = get_booking_for_update_by_id(session, link.booking_id) if lock else link.booking
    if booking is None or booking.reference != reference:
        return None
    return booking
