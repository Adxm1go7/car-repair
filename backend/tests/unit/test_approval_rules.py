"""When a request and an approval run out, and when there's enough time to ask or to pay."""

from datetime import UTC, datetime, timedelta

from app.bookings.approval import (
    enough_notice,
    enough_time_to_pay,
    needs_approval,
    payment_deadline,
    request_deadline,
)
from app.models import Service
from app.repositories.availability import ApprovalRules

RULES = ApprovalRules(hold_hours=48, payment_hours=24, lead_hours=24, min_payment_hours=2)
CUTOFF = 120
NOW = datetime(2026, 12, 1, 9, tzinfo=UTC)


def hours(n: float) -> timedelta:
    return timedelta(hours=n)


def test_far_off_request_waits_the_full_time() -> None:
    start = NOW + timedelta(days=7)
    assert request_deadline(NOW, start, RULES, CUTOFF) == NOW + hours(48)
    assert payment_deadline(NOW, start, RULES, CUTOFF) == NOW + hours(24)


def test_request_deadline_stops_at_the_cutoff() -> None:
    start = NOW + hours(30)
    assert request_deadline(NOW, start, RULES, CUTOFF) == NOW + hours(28)


def test_payment_deadline_stops_at_the_cutoff() -> None:
    start = NOW + hours(10)
    assert payment_deadline(NOW, start, RULES, CUTOFF) == NOW + hours(8)
    assert enough_time_to_pay(NOW, start, RULES, CUTOFF)


def test_less_than_two_hours_to_pay_is_too_soon() -> None:
    start = NOW + hours(4) - timedelta(minutes=1)
    assert payment_deadline(NOW, start, RULES, CUTOFF) == NOW + hours(2) - timedelta(minutes=1)
    assert not enough_time_to_pay(NOW, start, RULES, CUTOFF)
    assert enough_time_to_pay(NOW, NOW + hours(4), RULES, CUTOFF)


def test_requests_need_a_days_notice() -> None:
    assert enough_notice(NOW, NOW + hours(24), RULES)
    assert not enough_notice(NOW, NOW + hours(24) - timedelta(minutes=1), RULES)


def test_any_needs_approval_service_makes_it_a_request() -> None:
    instant = Service(approval_mode="instant")
    checked = Service(approval_mode="needs_approval")
    assert not needs_approval([instant])
    assert needs_approval([instant, checked])
