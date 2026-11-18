"""Which actions staff may take on a booking, and when. Pure: no database, no clock.

    confirmed   -> in progress  Start job       any time
    in progress -> completed    Complete job    any time
    confirmed   -> no show      Mark no show    only once the start time has passed
    in progress -> confirmed    Undo start      any time
    completed   -> in progress  Undo complete   within 24 hours of completing
    no show     -> confirmed    Undo no show    within 24 hours of marking

Only a confirmed booking can be moved or cancelled. A no-show keeps its deposit and its
time, and sends no email.
"""

from datetime import datetime, timedelta
from typing import Final, Literal
from zoneinfo import ZoneInfo

Action = Literal[
    "start", "complete", "no_show", "undo_start", "undo_complete", "undo_no_show", "move", "cancel"
]
StatusAction = Literal[
    "start", "complete", "no_show", "undo_start", "undo_complete", "undo_no_show"
]

UNDO_LIMIT: Final = timedelta(hours=24)

ACTION_TARGET: Final[dict[StatusAction, str]] = {
    "start": "in_progress",
    "complete": "completed",
    "no_show": "no_show",
    "undo_start": "confirmed",
    "undo_complete": "in_progress",
    "undo_no_show": "confirmed",
}


def _within_undo(status_changed_at: datetime | None, now: datetime) -> bool:
    return status_changed_at is not None and now <= status_changed_at + UNDO_LIMIT


def booking_actions(
    status: str, start_at: datetime, status_changed_at: datetime | None, now: datetime
) -> list[Action]:
    """The actions allowed now, in the order the page shows them."""
    actions: list[Action] = []
    if status == "confirmed":
        actions.append("start")
        if now >= start_at:
            actions.append("no_show")
        actions += ["move", "cancel"]
    elif status == "in_progress":
        actions += ["complete", "undo_start"]
    elif status == "completed" and _within_undo(status_changed_at, now):
        actions.append("undo_complete")
    elif status == "no_show" and _within_undo(status_changed_at, now):
        actions.append("undo_no_show")
    return actions


def starts_on_another_day(start_at: datetime, now: datetime, zone: ZoneInfo) -> bool:
    """Is the job booked for a different garage-local day? The page then asks before
    starting it, since a car may well arrive early but a wrong tap is also easy."""
    return start_at.astimezone(zone).date() != now.astimezone(zone).date()
