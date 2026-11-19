"""The three customer emails: what they say, in which time zone, and that they escape HTML."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.email.message import EmailTemplate
from app.email.render import (
    EmailContext,
    EnquiryEmailContext,
    StaffEmailContext,
    render_email,
    render_enquiry_email,
    render_staff_email,
)

LONDON = ZoneInfo("Europe/London")
START = datetime(2026, 11, 20, 9, tzinfo=UTC)  # Fri 20 Nov, 09:00 in London (GMT)
LINK = "http://localhost:8080/booking/ABCD-EFGH#t=secret-token"
GARAGE = {
    "name": "Test Garage",
    "address": "1 Test Street, Testtown",
    "phone": "000 111",
    "email": "garage@example.test",
}

CONTEXT = EmailContext(
    reference="ABCD-EFGH",
    customer_name="Sam Driver",
    start=START,
    end=START + timedelta(hours=1),
    zone=LONDON,
    services=["MOT test"],
    registration="AB12CDE",
    make="Ford",
    model="Focus",
    deposit_status="paid",
    deposit_pence=2000,
    free_cancellation_until=START - timedelta(hours=24),
    garage=GARAGE,
    link_url=LINK,
    now=START - timedelta(days=5),
)


def test_confirmation_has_link_and_free_cancellation_time() -> None:
    message = render_email("confirmation", "sam@example.com", CONTEXT)
    assert message.to == "sam@example.com"
    assert message.subject == "Your booking is confirmed — ABCD-EFGH"
    for body in (message.text, message.html):
        assert LINK in body
        assert "Fri 20 Nov, 09:00" in body
        assert "You can cancel free of charge until Thu 19 Nov, 09:00" in body
        assert "£20" in body


def test_reminder_subject_names_the_day() -> None:
    message = render_email("reminder", "sam@example.com", CONTEXT)
    assert message.subject == "See you on Fri 20 Nov — ABCD-EFGH"
    assert LINK in message.text


def test_reminder_after_window_says_call() -> None:
    late = replace(CONTEXT, now=START - timedelta(hours=20))
    message = render_email("reminder", "sam@example.com", late)
    assert "free of charge" not in message.text
    assert "To change or cancel, please call us on 000 111" in message.text


def test_html_escapes_customer_text() -> None:
    tricky = replace(CONTEXT, customer_name="<b>Sam & Co</b>")
    message = render_email("confirmation", "sam@example.com", tricky)
    assert "&lt;b&gt;Sam &amp; Co&lt;/b&gt;" in message.html
    assert "<b>Sam" not in message.html
    assert "<b>Sam & Co</b>" in message.text


def test_times_are_garage_local_across_clock_change() -> None:
    # Clocks go forward at 01:00 UTC on Sun 28 Mar 2027: 08:00 UTC is 09:00 BST.
    start = datetime(2027, 3, 28, 8, tzinfo=UTC)
    spring = replace(
        CONTEXT,
        start=start,
        end=start + timedelta(hours=1),
        free_cancellation_until=start - timedelta(hours=24),
        now=start - timedelta(days=5),
    )
    message = render_email("confirmation", "sam@example.com", spring)
    assert "Sun 28 Mar, 09:00" in message.text
    assert "until Sat 27 Mar, 08:00" in message.text  # 24 hours earlier, still GMT


@pytest.mark.parametrize(
    ("deposit_status", "expected"),
    [
        ("refund_pending", "Your £20 deposit is being refunded."),
        ("refunded", "Your £20 deposit is being refunded."),
        ("refund_failed", "We'll be in touch about your refund."),
        ("paid", "Your deposit has been kept"),
    ],
)
def test_cancellation_wording_per_deposit_status(deposit_status: str, expected: str) -> None:
    cancelled = replace(CONTEXT, deposit_status=deposit_status, link_url=None)
    message = render_email("cancellation", "sam@example.com", cancelled)
    assert message.subject == "Your booking is cancelled — ABCD-EFGH"
    assert expected in message.text
    assert "To book again, please call us on 000 111." in message.text


def test_cancellation_of_a_waived_booking_has_no_deposit_line() -> None:
    cancelled = replace(CONTEXT, deposit_status="waived", deposit_pence=0, link_url=None)
    message = render_email("cancellation", "sam@example.com", cancelled)
    assert "deposit" not in message.text.lower()
    assert "refund" not in message.text.lower()


TEMPLATES: list[EmailTemplate] = ["confirmation", "reminder", "cancellation"]


@pytest.mark.parametrize("template", TEMPLATES)
def test_garage_details_come_from_the_context(template: EmailTemplate) -> None:
    message = render_email(template, "sam@example.com", CONTEXT)
    for body in (message.text, message.html):
        assert "Test Garage" in body
        assert "1 Test Street, Testtown" in body
        assert "000 111" in body
        assert "Hillside" not in body
    assert "reschedule" not in message.text.lower()


# --- staff emails ---------------------------------------------------------------

STAFF_LINK = "http://localhost:8080/staff/set-password#t=secret-token"


def staff_context(**changes: str) -> StaffEmailContext:
    values = {"name": "Sam Staff", "link_url": STAFF_LINK, "valid_for": "72 hours", **changes}
    return StaffEmailContext(garage=GARAGE, **values)


def test_staff_invite_has_link_and_garage_name() -> None:
    message = render_staff_email("staff_invite", "sam@example.test", staff_context())
    assert message.subject == "You've been invited to Test Garage bookings"
    assert STAFF_LINK in message.text
    assert "72 hours" in message.text
    assert STAFF_LINK in message.html


def test_staff_invite_html_escapes_name() -> None:
    message = render_staff_email("staff_invite", "x@example.test", staff_context(name="<b>Sam</b>"))
    assert "&lt;b&gt;Sam&lt;/b&gt;" in message.html
    assert "<b>Sam</b>" in message.text


def test_reset_says_one_hour() -> None:
    message = render_staff_email(
        "password_reset", "x@example.test", staff_context(valid_for="1 hour")
    )
    assert message.subject == "Reset your password"
    assert "1 hour" in message.text
    assert "1 hour" in message.html


@pytest.mark.parametrize("template", ["confirmation", "cancellation"])
def test_no_deposit_line_for_not_required(template: EmailTemplate) -> None:
    message = render_email(
        template, "x@example.test", replace(CONTEXT, deposit_status="not_required")
    )
    for body in (message.text, message.html):
        assert "deposit" not in body.lower()


# --- garage changes -----------------------------------------------------------

MOVED = replace(
    CONTEXT,
    start=START + timedelta(hours=2),
    end=START + timedelta(hours=3),
    free_cancellation_until=START + timedelta(hours=2) - timedelta(hours=24),
    reason="Lift broken",
    previous_start=START,
    previous_end=START + timedelta(hours=1),
    previous_bay="MOT bay",
)


def test_moved_email_shows_old_and_new_time_and_reason() -> None:
    message = render_email("moved", "x@example.test", MOVED)
    assert message.subject == "Your booking has moved — ABCD-EFGH"
    for body in (message.text, message.html):
        assert "Fri 20 Nov, 09:00" in body  # was
        assert "Fri 20 Nov, 11:00" in body  # now
        assert "Lift broken" in body
        assert "000 111" in body
        assert LINK in body


def test_moved_email_without_reason_has_no_reason_line() -> None:
    message = render_email("moved", "x@example.test", replace(MOVED, reason=None))
    assert "Reason" not in message.text
    assert "Reason" not in message.html


def test_garage_cancellation_says_refund_and_reason() -> None:
    context = replace(CONTEXT, deposit_status="refund_pending", reason="Staff off sick")
    message = render_email("garage_cancellation", "x@example.test", context)
    assert message.subject == "We've had to cancel your booking — ABCD-EFGH"
    for body in (message.text, message.html):
        assert "Staff off sick" in body
        assert "£20 deposit is being refunded" in body
        assert "000 111" in body


def test_garage_cancellation_without_reason_or_deposit() -> None:
    context = replace(CONTEXT, deposit_status="not_required", reason=None)
    message = render_email("garage_cancellation", "x@example.test", context)
    assert "Reason" not in message.text
    assert "deposit" not in message.text.lower()


def test_reason_is_html_escaped() -> None:
    message = render_email("moved", "x@example.test", replace(MOVED, reason="<i>oops</i>"))
    assert "&lt;i&gt;oops&lt;/i&gt;" in message.html
    assert "<i>oops</i>" in message.text


# --- approval emails -------------------------------------------------------------

DEADLINE = datetime(2026, 11, 18, 9, tzinfo=UTC)  # Wed 18 Nov, 09:00 in London
APPROVAL = replace(
    CONTEXT, deposit_status="unpaid", deposit_pence=0, deposit_due_pence=2000, deadline=DEADLINE
)

APPROVAL_SUBJECTS: list[tuple[EmailTemplate, str]] = [
    ("request_received", "We've got your request — ABCD-EFGH"),
    ("approved", "Your booking is approved — pay the deposit to confirm — ABCD-EFGH"),
    ("proposed", "We've suggested a new time — ABCD-EFGH"),
    ("declined", "We can't take your booking — ABCD-EFGH"),
    ("request_expired", "Your request has lapsed — ABCD-EFGH"),
    ("deposit_expired", "Your booking time has been released — ABCD-EFGH"),
]


@pytest.mark.parametrize(("template", "subject"), APPROVAL_SUBJECTS)
def test_approval_email_subjects(template: EmailTemplate, subject: str) -> None:
    assert render_email(template, "sam@example.com", APPROVAL).subject == subject


@pytest.mark.parametrize("template", ["request_received", "approved", "proposed"])
def test_approval_emails_with_something_to_do_carry_the_link(template: EmailTemplate) -> None:
    message = render_email(template, "sam@example.com", APPROVAL)
    for body in (message.text, message.html):
        assert LINK in body
        assert "Wed 18 Nov, 09:00" in body


@pytest.mark.parametrize("template", ["approved", "proposed"])
def test_approval_asks_for_the_deposit_by_the_deadline(template: EmailTemplate) -> None:
    message = render_email(template, "sam@example.com", APPROVAL)
    for body in (message.text, message.html):
        assert "£20" in body
        assert "Wed 18 Nov, 09:00" in body


def test_proposal_shows_old_and_new_time() -> None:
    proposal = replace(
        APPROVAL,
        previous_start=START - timedelta(days=1),
        previous_end=START - timedelta(days=1) + timedelta(hours=1),
    )
    message = render_email("proposed", "sam@example.com", proposal)
    for body in (message.text, message.html):
        assert "Thu 19 Nov, 09:00" in body
        assert "Fri 20 Nov, 09:00" in body


def test_decline_shows_a_reason_only_when_given() -> None:
    with_reason = render_email("declined", "x@example.com", replace(APPROVAL, reason="No parts"))
    without = render_email("declined", "x@example.com", APPROVAL)
    assert "Reason: No parts" in with_reason.text
    assert "No parts" in with_reason.html
    assert "Reason" not in without.text
    assert "Reason" not in without.html


@pytest.mark.parametrize("template", ["declined", "request_expired", "deposit_expired"])
def test_approval_emails_with_nothing_to_do_say_call_us(template: EmailTemplate) -> None:
    message = render_email(template, "sam@example.com", replace(APPROVAL, link_url=None))
    for body in (message.text, message.html):
        assert "call us on 000 111" in body
        assert "secret-token" not in body
        assert "refund" not in body.lower()  # nothing was paid


def test_released_approval_paid_late_says_the_payment_is_refunded() -> None:
    late = replace(APPROVAL, deposit_status="refund_pending", link_url=None)
    message = render_email("deposit_expired", "sam@example.com", late)
    for body in (message.text, message.html):
        assert "Your £20 payment came in after the time was released, so we're refunding it" in body
        assert "Nothing has been charged" not in body


ENQUIRY = EnquiryEmailContext(
    customer_name="Sam Driver",
    registration="AB12CDE",
    make="Ford",
    model="Focus",
    description="Rattle from the front left when braking",
    reason=None,
    garage=GARAGE,
)


def test_render_enquiry_received() -> None:
    message = render_enquiry_email("enquiry_received", "sam@example.com", ENQUIRY)
    assert message.subject == "We've got your enquiry"
    assert message.to == "sam@example.com"
    for body in (message.text, message.html):
        assert "Sam Driver" in body
        assert "AB12CDE · Ford Focus" in body
        assert "Rattle from the front left when braking" in body
        assert "/booking/" not in body


def test_render_enquiry_declined_with_and_without_reason() -> None:
    with_reason = replace(ENQUIRY, reason="Too busy this month")
    message = render_enquiry_email("enquiry_declined", "sam@example.com", with_reason)
    assert message.subject == "We can't take on your enquiry"
    assert "Reason: Too busy this month" in message.text
    assert "Too busy this month" in message.html
    without = render_enquiry_email("enquiry_declined", "sam@example.com", ENQUIRY)
    assert "Reason" not in without.text
    assert "Reason" not in without.html
    for body in (message.text, message.html, without.text, without.html):
        assert "call us on 000 111" in body
        assert "/booking/" not in body


def test_enquiry_email_escapes_description() -> None:
    sneaky = replace(
        ENQUIRY, customer_name="<b>Sam</b>", description="<script>alert(1)</script> noise"
    )
    message = render_enquiry_email("enquiry_received", "sam@example.com", sneaky)
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in message.html
    assert "<script>" not in message.html
    assert "&lt;b&gt;Sam&lt;/b&gt;" in message.html
    assert "<script>alert(1)</script>" in message.text  # plain text is never escaped
