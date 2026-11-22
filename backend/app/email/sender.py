import smtplib
from email.message import EmailMessage
from typing import Protocol

from sqlalchemy.orm import Session

from app.email.message import OutgoingEmail
from app.models import DemoInboxEmail


class EmailUnavailable(Exception):
    """The email could not be handed to the mail server. The queue retries it later."""


class EmailSender(Protocol):
    def send(self, message: OutgoingEmail) -> None:
        """Send one email, or raise EmailUnavailable."""
        ...


class SmtpSender:
    """Sends through a plain SMTP server (Mailpit locally, the real relay in production)."""

    def __init__(self, host: str, port: int, from_address: str) -> None:
        self._host = host
        self._port = port
        self._from_address = from_address

    def send(self, message: OutgoingEmail) -> None:
        email = EmailMessage()
        email["From"] = self._from_address
        email["To"] = message.to
        email["Subject"] = message.subject
        email.set_content(message.text)
        email.add_alternative(message.html, subtype="html")
        try:
            with smtplib.SMTP(self._host, self._port, timeout=10) as smtp:
                smtp.send_message(email)
        except (smtplib.SMTPException, OSError) as error:
            where = f"{self._host}:{self._port}"
            raise EmailUnavailable(f"SMTP send to {where} failed: {error}") from error


class DemoInboxSender:
    """The live demo's sender: keeps the email for the Demo inbox page and sends nothing.

    It adds the row to the outbox's own session and never commits, so the row is saved with
    the email's "sent" status, or rolled back with it if the send is undone."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def send(self, message: OutgoingEmail) -> None:
        self._session.add(
            DemoInboxEmail(
                template=message.template,
                recipient=message.to,
                subject=message.subject,
                text=message.text,
                html=message.html,
            )
        )
        self._session.flush()
