"""Pure payment rules: no database, no provider."""

from datetime import datetime, timedelta
from typing import Literal

CancelledBy = Literal["customer", "garage"]


def deposit_refundable(
    start_at: datetime, now: datetime, free_cancellation_hours: int, by: CancelledBy
) -> bool:
    """A customer cancelling at least `free_cancellation_hours` before the start gets the
    deposit back (exactly at the boundary counts as in time). The garage always refunds."""
    if by == "garage":
        return True
    return now <= start_at - timedelta(hours=free_cancellation_hours)
