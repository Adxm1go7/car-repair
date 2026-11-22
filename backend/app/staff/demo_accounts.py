"""The live demo's two shared logins (DEMO_STAFF), whose emails and passwords are public.

On the demo site nobody may lock them (the per-email lockout skips them; the per-IP one
still counts), reset their password, or change their role or whether they're active.
Otherwise one visitor could shut every other visitor out until the nightly reset.
"""

from typing import Final

from app.config import AppConfig
from app.demo_data import DEMO_STAFF
from app.staff.throttle import normalise_email

DEMO_ACCOUNT_LOCKED: Final = "The demo logins can't be changed"
_DEMO_EMAILS: Final = frozenset(normalise_email(staff.email) for staff in DEMO_STAFF)


def is_demo_account(config: AppConfig, email: str) -> bool:
    return config.demo_site and normalise_email(email) in _DEMO_EMAILS
