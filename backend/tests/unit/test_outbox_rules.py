"""The outbox's pure rules: how long to wait before a retry, and whether an email still applies."""

from datetime import timedelta

import pytest

from app.email.message import EmailTemplate
from app.email.outbox import email_still_applies, link_url, next_attempt_delay


@pytest.mark.parametrize(("attempts", "minutes"), [(1, 1), (2, 5), (3, 15), (4, 60), (9, 60)])
def test_retry_delays(attempts: int, minutes: int) -> None:
    assert next_attempt_delay(attempts) == timedelta(minutes=minutes)


@pytest.mark.parametrize(
    ("template", "status", "applies"),
    [
        ("confirmation", "confirmed", True),
        ("confirmation", "cancelled", False),
        ("confirmation", "completed", False),
        ("reminder", "confirmed", True),
        ("reminder", "cancelled", False),
        ("reminder", "no_show", False),
        ("cancellation", "cancelled", True),
        ("cancellation", "confirmed", False),
    ],
)
def test_email_still_applies(template: EmailTemplate, status: str, applies: bool) -> None:
    assert email_still_applies(template, status) is applies


def test_link_url_puts_token_in_fragment() -> None:
    assert link_url("http://x/", "ABCD-EFGH", "tok") == "http://x/booking/ABCD-EFGH#t=tok"
    assert link_url("http://x", "ABCD-EFGH", "tok") == "http://x/booking/ABCD-EFGH#t=tok"
