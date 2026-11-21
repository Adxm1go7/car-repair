"""Turning a booking into an email. Pure: no database, no clock, no network.

The `.txt.j2` templates are plain text and never escaped. The `.html.j2` ones are
autoescaped, so a customer's name or notes can't add markup to the HTML email.
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from app.email.message import EmailTemplate, EnquiryTemplate, OutgoingEmail, StaffTemplate


@dataclass(frozen=True)
class EmailContext:
    """Everything an email says. Times are aware; the templates show them in `zone`."""

    reference: str
    customer_name: str
    start: datetime
    end: datetime
    zone: ZoneInfo
    services: list[str]
    registration: str
    make: str
    model: str
    deposit_status: str
    deposit_pence: int
    free_cancellation_until: datetime
    garage: dict[str, str]  # name, address, phone, email: the garage_contact setting
    link_url: str | None
    now: datetime  # when the email is rendered: is free cancellation still open?
    # Garage changes: why, and for a move, where and when it was before.
    reason: str | None = None
    previous_start: datetime | None = None
    previous_end: datetime | None = None
    previous_bay: str | None = None
    # Requests and approvals: when staff will answer by, or when the deposit is due by.
    deadline: datetime | None = None
    deposit_due_pence: int = 0  # the deposit an approval asks for


@dataclass(frozen=True)
class StaffEmailContext:
    """Everything a staff account email says."""

    name: str
    garage: dict[str, str]  # the garage_contact setting
    link_url: str  # the set-password link, with its token
    valid_for: str  # "72 hours" or "1 hour"


@dataclass(frozen=True)
class EnquiryEmailContext:
    """Everything an enquiry email says: what the customer sent, and why it was declined."""

    customer_name: str
    registration: str
    make: str
    model: str
    description: str
    reason: str | None
    garage: dict[str, str]  # the garage_contact setting


ENQUIRY_SUBJECTS: dict[EnquiryTemplate, str] = {
    "enquiry_received": "We've got your enquiry",
    "enquiry_declined": "We can't take on your enquiry",
}

STAFF_SUBJECTS: dict[StaffTemplate, str] = {
    "staff_invite": "You've been invited to {garage} bookings",
    "password_reset": "Reset your password",
}

SUBJECTS: dict[EmailTemplate, str] = {
    "confirmation": "Your booking is confirmed — {reference}",
    "reminder": "See you on {day} — {reference}",
    "cancellation": "Your booking is cancelled — {reference}",
    "moved": "Your booking has moved — {reference}",
    "garage_cancellation": "We've had to cancel your booking — {reference}",
    "request_received": "We've got your request — {reference}",
    "approved": "Your booking is approved — pay the deposit to confirm — {reference}",
    "proposed": "We've suggested a new time — {reference}",
    "declined": "We can't take your booking — {reference}",
    "request_expired": "Your request has lapsed — {reference}",
    "deposit_expired": "Your booking time has been released — {reference}",
}


def format_day(value: datetime, zone: ZoneInfo) -> str:
    """Like "Fri 20 Nov"."""
    local = value.astimezone(zone)
    return f"{local:%a} {local.day} {local:%b}"


def format_moment(value: datetime, zone: ZoneInfo) -> str:
    """Like "Fri 20 Nov, 09:00"."""
    return f"{format_day(value, zone)}, {value.astimezone(zone):%H:%M}"


def format_pounds(pence: int) -> str:
    """Like "£20", or "£20.50" when there are pence."""
    pounds, rest = divmod(pence, 100)
    return f"£{pounds}" if rest == 0 else f"£{pounds}.{rest:02d}"


_environment = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(enabled_extensions=("html.j2",), default=False),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
)


def render_email(template: EmailTemplate, to: str, context: EmailContext) -> OutgoingEmail:
    zone = context.zone
    values = {
        "c": context,
        "when": format_moment(context.start, zone),
        "ends": f"{context.end.astimezone(zone):%H:%M}",
        "free_until": format_moment(context.free_cancellation_until, zone),
        "can_cancel_free": context.now <= context.free_cancellation_until,
        "deposit": format_pounds(context.deposit_pence),
        "notice_hours": round((context.start - context.free_cancellation_until).total_seconds())
        // 3600,
        "was": format_moment(context.previous_start, zone) if context.previous_start else "",
        "was_ends": f"{context.previous_end.astimezone(zone):%H:%M}"
        if context.previous_end
        else "",
        "deadline": format_moment(context.deadline, zone) if context.deadline else "",
        "deposit_due": format_pounds(context.deposit_due_pence),
    }
    subject = SUBJECTS[template].format(
        reference=context.reference, day=format_day(context.start, zone)
    )
    return OutgoingEmail(
        to=to,
        subject=subject,
        text=_environment.get_template(f"{template}.txt.j2").render(values),
        html=_environment.get_template(f"{template}.html.j2").render(values),
        template=template,
    )


def render_staff_email(
    template: StaffTemplate, to: str, context: StaffEmailContext
) -> OutgoingEmail:
    values = {"c": context}
    return OutgoingEmail(
        to=to,
        subject=STAFF_SUBJECTS[template].format(garage=context.garage.get("name", "")),
        text=_environment.get_template(f"{template}.txt.j2").render(values),
        html=_environment.get_template(f"{template}.html.j2").render(values),
        template=template,
    )


def render_enquiry_email(
    template: EnquiryTemplate, to: str, context: EnquiryEmailContext
) -> OutgoingEmail:
    values = {"c": context}
    return OutgoingEmail(
        to=to,
        subject=ENQUIRY_SUBJECTS[template],
        text=_environment.get_template(f"{template}.txt.j2").render(values),
        html=_environment.get_template(f"{template}.html.j2").render(values),
        template=template,
    )
