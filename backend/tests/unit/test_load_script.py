"""The load test's own arithmetic: nearest-rank percentiles and the next open day."""

from datetime import date

from scripts.load_availability import next_open_day, percentile


def test_percentile_is_nearest_rank() -> None:
    assert percentile([10, 20, 30, 40], 50) == 20
    assert percentile([10, 20, 30, 40], 99) == 40
    assert percentile([10, 20, 30, 40], 1) == 10


def test_percentile_of_nothing_is_zero() -> None:
    assert percentile([], 95) == 0


def test_next_open_day_skips_closed_days_and_uses_the_timetable_in_force() -> None:
    timetables = [
        {"starts_on": "2000-01-01", "days": [{"weekday": 0}, {"weekday": 2}]},  # Mon, Wed
        {"starts_on": "2027-01-01", "days": [{"weekday": 4}]},  # Fri, later on
    ]
    # Tuesday 10 Nov 2026: tomorrow, Wednesday, is the next open day.
    assert next_open_day(timetables, date(2026, 11, 10)) == date(2026, 11, 11)
    # Wednesday 11 Nov: not today, the next is Monday 16 Nov.
    assert next_open_day(timetables, date(2026, 11, 11)) == date(2026, 11, 16)
