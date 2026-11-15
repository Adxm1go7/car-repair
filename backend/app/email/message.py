from dataclasses import dataclass
from typing import Literal

# The same names as EMAIL_TEMPLATES in app/models/email.py.
EmailTemplate = Literal["confirmation", "reminder", "cancellation"]


@dataclass(frozen=True)
class OutgoingEmail:
    """One rendered email, ready to send: a plain-text and an HTML version of the same words."""

    to: str
    subject: str
    text: str
    html: str
