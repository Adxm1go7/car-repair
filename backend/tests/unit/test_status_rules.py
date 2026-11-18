"""Which job-status changes and booking actions staff may take, and when."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.schedule.status_rules import (
    ACTION_TARGET,
    UNDO_LIMIT,
    booking_actions,
    starts_on_another_day,
)

LONDON = ZoneInfo("Europe/London")
START = datetime(2026, 11, 20, 9, tzinfo=UTC)
BEFORE = START - timedelta(days=2)
CHANGED = START + timedelta(hours=1)


def test_confirmed_before_start_can_start_move_and_cancel() -> None:
    assert booking_actions("confirmed", START, None, BEFORE) == ["start", "move", "cancel"]


def test_confirmed_after_start_can_also_be_a_no_show() -> None:
    assert booking_actions("confirmed", START, None, START) == [
        "start",
        "no_show",
        "move",
        "cancel",
    ]


def test_no_show_not_before_start() -> None:
    assert "no_show" not in booking_actions("confirmed", START, None, START - timedelta(seconds=1))
    assert "no_show" in booking_actions("confirmed", START, None, START)


def test_in_progress_can_complete_or_undo_start_any_time() -> None:
    later = CHANGED + timedelta(days=10)
    assert booking_actions("in_progress", START, CHANGED, later) == ["complete", "undo_start"]


def test_undo_complete_until_24_hours() -> None:
    assert booking_actions("completed", START, CHANGED, CHANGED + UNDO_LIMIT) == ["undo_complete"]
    assert (
        booking_actions("completed", START, CHANGED, CHANGED + UNDO_LIMIT + timedelta(seconds=1))
        == []
    )


def test_undo_no_show_until_24_hours() -> None:
    assert booking_actions("no_show", START, CHANGED, CHANGED + timedelta(hours=23)) == [
        "undo_no_show"
    ]
    assert booking_actions("no_show", START, CHANGED, CHANGED + timedelta(hours=25)) == []


def test_no_undo_without_a_recorded_change() -> None:
    assert booking_actions("completed", START, None, CHANGED) == []


@pytest.mark.parametrize("status", ["held", "pending_approval", "cancelled", "expired"])
def test_nothing_for_other_statuses(status: str) -> None:
    assert booking_actions(status, START, CHANGED, CHANGED) == []


def test_action_targets() -> None:
    assert ACTION_TARGET == {
        "start": "in_progress",
        "complete": "completed",
        "no_show": "no_show",
        "undo_start": "confirmed",
        "undo_complete": "in_progress",
        "undo_no_show": "confirmed",
    }


def test_another_day_uses_garage_local_dates() -> None:
    start = datetime(2027, 3, 29, 8, tzinfo=UTC)  # 09:00 BST on Monday 29 March
    late_sunday = datetime(2027, 3, 28, 22, 30, tzinfo=UTC)  # 23:30 BST on Sunday
    just_after_midnight = datetime(2027, 3, 28, 23, 30, tzinfo=UTC)  # 00:30 BST on Monday
    assert starts_on_another_day(start, late_sunday, LONDON)
    assert not starts_on_another_day(start, just_after_midnight, LONDON)
