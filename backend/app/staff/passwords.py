"""Staff passwords: argon2id hashes, and the one rule a password must meet (its length)."""

from typing import Final

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

MIN_PASSWORD_LENGTH: Final = 8
# Long enough for any passphrase; short enough that hashing it costs nothing extra.
MAX_PASSWORD_LENGTH: Final = 200

_hasher = PasswordHasher()


def clean_password(value: str) -> str:
    """The password as typed (spaces are kept), or ValueError with a message to show."""
    if len(value) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Your password must be at least {MIN_PASSWORD_LENGTH} characters")
    if len(value) > MAX_PASSWORD_LENGTH:
        raise ValueError(f"Your password must be at most {MAX_PASSWORD_LENGTH} characters")
    return value


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def password_matches(password: str, stored: str | None) -> bool:
    """False for no hash, a wrong password or a damaged hash. Never raises."""
    if stored is None:
        return False
    try:
        return _hasher.verify(stored, password)
    except (VerificationError, InvalidHashError):
        return False
