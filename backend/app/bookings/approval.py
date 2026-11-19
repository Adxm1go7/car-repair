"""The time rules for a booking that needs approval. Pure: no database, no clock.

A request waits up to `hold_hours` for staff, and an approval up to `payment_hours` for the
deposit, but neither past the booking cut-off before the start. A request needs
`lead_hours` of notice, and staff can't approve unless the customer gets at least
`min_payment_hours` to pay.
"""

from collections.abc import Sequence
from datetime import datetime, timedelta

from app.models import Service
from app.repositories.availability import ApprovalRules


def needs_approval(services: Sequence[Service]) -> bool:
    """If any service needs approval, the whole visit is a request."""
    return any(service.approval_mode == "needs_approval" for service in services)


def _latest(start: datetime, cutoff_minutes: int) -> datetime:
    return start - timedelta(minutes=cutoff_minutes)


def request_deadline(
    now: datetime, start: datetime, rules: ApprovalRules, cutoff_minutes: int
) -> datetime:
    return min(now + timedelta(hours=rules.hold_hours), _latest(start, cutoff_minutes))


def payment_deadline(
    now: datetime, start: datetime, rules: ApprovalRules, cutoff_minutes: int
) -> datetime:
    return min(now + timedelta(hours=rules.payment_hours), _latest(start, cutoff_minutes))


def enough_notice(now: datetime, start: datetime, rules: ApprovalRules) -> bool:
    return start >= now + timedelta(hours=rules.lead_hours)


def enough_time_to_pay(
    now: datetime, start: datetime, rules: ApprovalRules, cutoff_minutes: int
) -> bool:
    deadline = payment_deadline(now, start, rules, cutoff_minutes)
    return deadline >= now + timedelta(hours=rules.min_payment_hours)
