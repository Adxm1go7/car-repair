"""Set-password links: an invite (72 hours) or a reset (1 hour). Each works once.

Only the token's hash is stored. The worker makes the token when it sends the email, so
the plain token never touches the database. Issuing a link cancels the person's other
unused ones, so only the newest email works. Nothing here commits.
"""

from datetime import datetime, timedelta
from typing import Final, Literal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.bookings.rules import hash_token, new_hold_token
from app.models import PasswordToken, StaffUser

Purpose = Literal["invite", "reset"]

LINK_LIFETIME: Final[dict[Purpose, timedelta]] = {
    "invite": timedelta(hours=72),
    "reset": timedelta(hours=1),
}
VALID_FOR: Final[dict[Purpose, str]] = {"invite": "72 hours", "reset": "1 hour"}
MAX_TOKEN_LENGTH: Final = 100  # a real token is 43 characters


def issue_password_token(session: Session, user: StaffUser, purpose: Purpose, now: datetime) -> str:
    """A new link for `user`, returning its plain token. Their older unused links stop working."""
    session.execute(
        delete(PasswordToken).where(
            PasswordToken.staff_user_id == user.id, PasswordToken.used_at.is_(None)
        )
    )
    token = new_hold_token()
    session.add(
        PasswordToken(
            staff_user_id=user.id,
            purpose=purpose,
            token_hash=hash_token(token),
            expires_at=now + LINK_LIFETIME[purpose],
        )
    )
    session.flush()
    return token


def use_password_token(session: Session, token: str, now: datetime) -> StaffUser | None:
    """Spend the link and return its user, or None if it's unknown, used, expired or the
    user was removed. The row is locked, so two tabs can't both use one link."""
    if len(token) > MAX_TOKEN_LENGTH:
        return None
    row = session.scalars(
        select(PasswordToken).where(PasswordToken.token_hash == hash_token(token)).with_for_update()
    ).one_or_none()
    if row is None or row.used_at is not None or now >= row.expires_at:
        return None
    if not row.staff_user.active:
        return None
    row.used_at = now
    session.flush()
    return row.staff_user


def set_password_url(base_url: str, token: str) -> str:
    # In the fragment, like booking links: browsers never send it to a server or a log.
    return f"{base_url.rstrip('/')}/staff/set-password#t={token}"
