"""Clock-change days in Europe/London: 23 hours in March, 25 hours in October."""

from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from app.availability.engine import (
    BayInfo,
    DayAvailability,
    DayHours,
    Policy,
    ServiceInfo,
    find_slots,
)

ZONE = ZoneInfo("Europe/London")
NOW = datetime(2026, 1, 1, tzinfo=UTC)
BAYS = [BayInfo(id=1, bay_type_id=1)]
ONE_HOUR_JOB = [ServiceInfo(id=1, duration_minutes=60, bay_type_id=1)]
RULES = Policy(zone=ZONE, grid_minutes=30, buffer_minutes=0, cutoff_minutes=0)
WEEKDAY = DayHours(time(8), time(17, 30), ((time(12, 30), time(13)),))


def run(day: date, hours: DayHours) -> DayAvailability:
    return find_slots(day, ONE_HOUR_JOB, BAYS, hours, [], RULES, NOW)


def iso_starts(result: DayAvailability) -> list[str]:
    return [slot.start.isoformat() for slot in result.slots]


def test_spring_forward_skips_missing_times_and_measures_elapsed_time() -> None:
    # 2027-03-28: clocks jump from 01:00 GMT to 02:00 BST, so 01:00-01:59 never happens.
    result = run(date(2027, 3, 28), DayHours(time(0), time(4)))
    assert iso_starts(result) == [
        "2027-03-28T00:00:00+00:00",
        "2027-03-28T00:30:00+00:00",
        "2027-03-28T02:00:00+01:00",
        "2027-03-28T02:30:00+01:00",
        "2027-03-28T03:00:00+01:00",
    ]
    # 00:30 GMT plus one real hour is 01:30 UTC, which is 02:30 BST.
    assert result.slots[1].end.isoformat() == "2027-03-28T02:30:00+01:00"


def test_fall_back_uses_first_occurrence_and_never_duplicates() -> None:
    # 2026-10-25: clocks go back from 02:00 BST to 01:00 GMT, so 01:00-01:59 happens twice.
    result = run(date(2026, 10, 25), DayHours(time(0), time(3)))
    assert iso_starts(result) == [
        "2026-10-25T00:00:00+01:00",
        "2026-10-25T00:30:00+01:00",
        "2026-10-25T01:00:00+01:00",
        "2026-10-25T01:30:00+01:00",
        "2026-10-25T02:00:00+00:00",
    ]


def test_demo_hours_carry_the_right_offset() -> None:
    assert iso_starts(run(date(2026, 10, 23), WEEKDAY))[0] == "2026-10-23T08:00:00+01:00"
    assert iso_starts(run(date(2026, 10, 26), WEEKDAY))[0] == "2026-10-26T08:00:00+00:00"
