from dataclasses import dataclass
from typing import Literal

# Together, the same names as EMAIL_TEMPLATES in app/models/email.py.
# Emails to a customer, about a booking:
EmailTemplate = Literal["confirmation", "reminder", "cancellation", "moved", "garage_cancellation"]
# Emails to a staff member, about their account:
StaffTemplate = Literal["staff_invite", "password_reset"]


@dataclass(frozen=True)
class OutgoingEmail:
    """One rendered email, ready to send: a plain-text and an HTML version of the same words."""

    to: str
    subject: str
    text: str
    html: str
