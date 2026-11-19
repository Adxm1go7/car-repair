"""Whether a booking fits a day's opening hours: the rule behind the hours clash check."""

from datetime import datetime, time
from zoneinfo import ZoneInfo

from app.repositories.hours import CLOSED, WeekdayHours
from app.settings.clashes import fits

LONDON = ZoneInfo("Europe/London")
WEEKDAY = WeekdayHours(time(8), time(17, 30), ((time(12, 30), time(13)),))


def local(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 12, 1, hour, minute, tzinfo=LONDON)


def test_fits_inside_hours() -> None:
    assert fits(WEEKDAY, local(8), local(9))
    assert fits(WEEKDAY, local(16, 30), local(17, 30))  # ends exactly at closing


def test_starts_before_opening() -> None:
    assert not fits(WEEKDAY, local(7, 30), local(8, 30))


def test_ends_after_closing() -> None:
    assert not fits(WEEKDAY, local(17), local(18))


def test_overlaps_break() -> None:
    assert not fits(WEEKDAY, local(12), local(13))
    assert not fits(WEEKDAY, local(12, 45), local(13, 15))


def test_touching_a_break_fits() -> None:
    assert fits(WEEKDAY, local(11, 30), local(12, 30))
    assert fits(WEEKDAY, local(13), local(14))


def test_closed_day_never_fits() -> None:
    assert not fits(CLOSED, local(9), local(10))


def test_running_past_midnight_never_fits() -> None:
    late = WeekdayHours(time(8), time(23, 30), ())
    assert not fits(late, local(23), datetime(2026, 12, 2, 0, 30, tzinfo=LONDON))
