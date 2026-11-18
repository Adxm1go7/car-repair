"""Staff accounts, their login sessions, set-password links and login attempts.

Only hashes are stored: a password's argon2 hash, and the SHA-256 of each session and link
token. Removing someone sets `active` to false rather than deleting the row, so the audit
log can still name who did what.
"""

from datetime import datetime
from typing import Final

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, func, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

STAFF_ROLES: Final[tuple[str, ...]] = ("admin", "staff")
PASSWORD_PURPOSES: Final[tuple[str, ...]] = ("invite", "reset")


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


class StaffUser(Base):
    __tablename__ = "staff_users"
    __table_args__ = (CheckConstraint(f"role IN ({_quoted(STAFF_ROLES)})", name="role_valid"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(254), unique=True)  # stored lowercase
    password_hash: Mapped[str | None] = mapped_column(String(200))  # None until a link is used
    role: Mapped[str] = mapped_column(String(10))
    active: Mapped[bool] = mapped_column(Boolean, server_default=true())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class StaffSession(Base):
    __tablename__ = "staff_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    staff_user_id: Mapped[int] = mapped_column(ForeignKey("staff_users.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # the 30-day cap

    staff_user: Mapped[StaffUser] = relationship()


class PasswordToken(Base):
    """A set-password link: an invite or a reset. Works once, until `expires_at`."""

    __tablename__ = "password_tokens"
    __table_args__ = (
        CheckConstraint(f"purpose IN ({_quoted(PASSWORD_PURPOSES)})", name="purpose_valid"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    staff_user_id: Mapped[int] = mapped_column(ForeignKey("staff_users.id", ondelete="CASCADE"))
    purpose: Mapped[str] = mapped_column(String(10))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    staff_user: Mapped[StaffUser] = relationship()


class LoginAttempt(Base):
    """One login or forgot-password attempt, counted for the lockout. The worker prunes them."""

    __tablename__ = "login_attempts"
    __table_args__ = (
        Index("ix_login_attempts_email_at", "email", "at"),
        Index("ix_login_attempts_ip_at", "ip", "at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254))  # lowercase, as typed
    ip: Mapped[str] = mapped_column(String(45))
    succeeded: Mapped[bool] = mapped_column(Boolean)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
