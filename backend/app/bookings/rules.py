"""Rules for what a customer types in, and the booking reference and hold token.

Each `clean_*` function trims, checks and normalises one field, raising `ValueError` with a
message the customer can act on. The frontend checks the same rules; these are the authority.
"""

import hashlib
import hmac
import re
import secrets
from datetime import datetime
from typing import Final

from app.payments.rules import deposit_refundable

# No 0/O or 1/I/L, so a reference read out over the phone can't be misheard.
REFERENCE_ALPHABET: Final = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"

PHONE_CHARACTERS = re.compile(r"[0-9 +()\-]+")
REGISTRATION = re.compile(r"[A-Z0-9]{2,8}")


def new_reference() -> str:
    """Eight characters shown as XXXX-XXXX. Not a secret: the hold token is."""
    chars = "".join(secrets.choice(REFERENCE_ALPHABET) for _ in range(8))
    return f"{chars[:4]}-{chars[4:]}"


def new_hold_token() -> str:
    return secrets.token_urlsafe(32)


def customer_can_cancel(
    status: str, start_at: datetime, now: datetime, free_cancellation_hours: int
) -> bool:
    """A customer may cancel a confirmed booking only while the deposit would come back. A
    request, or an approval not paid yet, can be cancelled at any time: nothing is paid."""
    if status in ("pending_approval", "awaiting_deposit"):
        return True
    return status == "confirmed" and deposit_refundable(
        start_at, now, free_cancellation_hours, "customer"
    )


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def token_matches(token: str, stored_hash: str | None) -> bool:
    """Constant-time, so response timing doesn't leak how much of a guess was right."""
    if stored_hash is None:
        return False
    return hmac.compare_digest(hash_token(token), stored_hash)


def reject_control_chars(value: str) -> str:
    """A NUL can't be stored in PostgreSQL text, so refuse it instead of failing later."""
    if "\x00" in value:
        raise ValueError("Please remove unusual characters")
    return value


def _length(value: str, low: int, high: int, what: str) -> str:
    value = reject_control_chars(value).strip()
    if not value:
        raise ValueError(f"Please enter your {what}")
    if not low <= len(value) <= high:
        raise ValueError(f"Your {what} must be {low}–{high} characters")
    return value


def clean_name(value: str) -> str:
    return _length(value, 1, 100, "name")


def clean_phone(value: str) -> str:
    value = value.strip()
    digits = sum(char.isdigit() for char in value)
    if not 7 <= len(value) <= 20 or not PHONE_CHARACTERS.fullmatch(value) or digits < 7:
        raise ValueError("Please enter a phone number we can call")
    return value


def clean_email(value: str) -> str:
    value = reject_control_chars(value).strip().lower()
    local, at, domain = value.partition("@")
    if (
        len(value) > 254
        or not at
        or not local
        or "@" in domain
        or "." not in domain.strip(".")
        or any(char.isspace() for char in value)
    ):
        raise ValueError("Please enter a valid email address")
    return value


def clean_registration(value: str) -> str:
    value = "".join(value.split()).upper()
    if not REGISTRATION.fullmatch(value):
        raise ValueError("Please enter your registration, 2–8 letters or numbers")
    return value


def clean_make_or_model(value: str) -> str:
    return _length(value, 1, 50, "car make and model")


def clean_notes(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    value = reject_control_chars(value).strip()
    if len(value) > 1000:
        raise ValueError("Notes can be at most 1000 characters")
    return value
