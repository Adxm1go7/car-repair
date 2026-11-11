"""The availability engine: every rule from the Milestone 3 design, on plain data."""

from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.availability.engine import (
    BayInfo,
    DayAvailability,
    DayHours,
    Occupied,
    Policy,
    ServiceInfo,
    find_slots,
)

ZONE = ZoneInfo("Europe/London")
DAY = date(2026, 11, 10)  # a Tuesday in GMT, so local time equals UTC
NOW = datetime(2026, 11, 1, tzinfo=UTC)
WEEKDAY = DayHours(time(8), time(17, 30), ((time(12, 30), time(13)),))
NO_BREAKS = DayHours(time(8), time(17, 30))

GENERAL, MOT = 1, 2
GENERAL_BAYS = (BayInfo(1, GENERAL), BayInfo(2, GENERAL), BayInfo(3, GENERAL))
MOT_BAY = BayInfo(10, MOT)
ALL_BAYS = (*GENERAL_BAYS, MOT_BAY)


def policy(grid: int = 30, buffer: int = 15, cutoff: int = 120) -> Policy:
    return Policy(zone=ZONE, grid_minutes=grid, buffer_minutes=buffer, cutoff_minutes=cutoff)


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(DAY.year, DAY.month, DAY.day, hour, minute, tzinfo=ZONE)


def general(minutes: int, service_id: int = 100) -> ServiceInfo:
    return ServiceInfo(id=service_id, duration_minutes=minutes, bay_type_id=GENERAL)


def mot(minutes: int = 60) -> ServiceInfo:
    return ServiceInfo(id=200, duration_minutes=minutes, bay_type_id=MOT)


def occupied(bay_id: int, start: datetime, end: datetime) -> Occupied:
    return Occupied(bay_id=bay_id, start=start, end=end)


def run(
    *services: ServiceInfo,
    hours: DayHours | None = WEEKDAY,
    taken: Sequence[Occupied] = (),
    rules: Policy | None = None,
    now: datetime = NOW,
) -> DayAvailability:
    return find_slots(DAY, services, ALL_BAYS, hours, taken, rules or policy(), now)


def starts(result: DayAvailability) -> list[str]:
    return [slot.start.strftime("%H:%M") for slot in result.slots]


def grid(first: str, last: str) -> list[str]:
    """Every half hour from first to last, inclusive, as "HH:MM"."""
    current = datetime.strptime(first, "%H:%M")
    end = datetime.strptime(last, "%H:%M")
    times = []
    while current <= end:
        times.append(current.strftime("%H:%M"))
        current += timedelta(minutes=30)
    return times


def slot_at(result: DayAvailability, hhmm: str) -> tuple[datetime, datetime, tuple[int, ...]]:
    slot = next(s for s in result.slots if s.start.strftime("%H:%M") == hhmm)
    return slot.start, slot.end, slot.bay_ids


# --- the grid, closing time and breaks ------------------------------------------


def test_mot_offers_grid_starts_except_inside_lunch() -> None:
    result = run(mot())
    assert starts(result) == grid("08:00", "12:00") + grid("13:00", "16:30")
    assert len(result.slots) == 17


def test_slot_has_real_end_and_every_free_bay() -> None:
    assert slot_at(run(general(180)), "08:00") == (at(8), at(11), (1, 2, 3))


def test_job_must_finish_by_closing() -> None:
    assert starts(run(general(180)))[-1] == "14:30"


def test_job_may_end_exactly_at_closing() -> None:
    result = starts(run(general(60)))
    assert "16:30" in result
    assert "17:00" not in result


def test_job_runs_through_lunch_with_unchanged_end() -> None:
    result = run(general(360))
    assert starts(result) == grid("08:00", "11:30")
    assert slot_at(result, "08:00")[1] == at(14)


def test_no_start_inside_a_break() -> None:
    result = starts(run(general(30)))
    assert "12:00" in result
    assert "13:00" in result
    assert "12:30" not in result


def test_duration_longer_than_the_day_gives_no_slots() -> None:
    result = run(general(600))
    assert result.slots == ()
    assert result.unavailable_reason is None


# --- the buffer -------------------------------------------------------------------


def test_previous_jobs_buffer_delays_the_next_start() -> None:
    result = run(mot(), taken=[occupied(10, at(8), at(9, 15))])
    assert starts(result)[0] == "09:30"


def test_own_buffer_cannot_overlap_the_next_reservation() -> None:
    result = starts(run(mot(), taken=[occupied(10, at(10), at(11))]))
    assert "08:30" in result
    assert "09:00" not in result


def test_zero_buffer_allows_back_to_back() -> None:
    taken = [occupied(10, at(8), at(9)), occupied(10, at(10), at(11))]
    assert "09:00" in starts(run(mot(), taken=taken, rules=policy(buffer=0)))


def test_buffer_cannot_overlap_a_block() -> None:
    assert "09:00" not in starts(run(mot(), taken=[occupied(10, at(10), at(12))]))


# --- blocks and competing bays ------------------------------------------------------


def test_full_day_block_on_one_bay_removes_only_that_bay() -> None:
    result = run(general(60), taken=[occupied(1, at(8), at(17, 30))])
    assert result.slots
    assert all(slot.bay_ids == (2, 3) for slot in result.slots)


def test_partial_block_on_one_bay() -> None:
    result = run(general(60), taken=[occupied(1, at(8), at(10))])
    assert slot_at(result, "08:00")[2] == (2, 3)
    assert slot_at(result, "10:00")[2] == (1, 2, 3)


def test_block_on_all_bays_gives_no_slots() -> None:
    taken = [occupied(bay.id, at(8), at(17, 30)) for bay in GENERAL_BAYS]
    assert run(general(60), taken=taken).slots == ()


def test_other_bay_types_are_ignored() -> None:
    result = run(general(60), taken=[occupied(10, at(8), at(17, 30))])
    assert len(result.slots) == 17
    assert all(10 not in slot.bay_ids for slot in result.slots)


def test_long_job_fits_fewer_bays_than_short_job() -> None:
    taken = [occupied(1, at(11), at(12))]
    assert slot_at(run(general(180), taken=taken), "08:00")[2] == (2, 3)
    assert slot_at(run(general(60), taken=taken), "08:00")[2] == (1, 2, 3)


# --- several services ---------------------------------------------------------------


def test_mixed_bay_types_give_reason_and_no_slots() -> None:
    result = run(mot(60), general(180))
    assert result.slots == ()
    assert result.unavailable_reason == "mixed_bay_types"
    assert result.duration_minutes == 240


def test_durations_are_summed() -> None:
    result = run(general(180, service_id=1), general(90, service_id=2))
    assert result.duration_minutes == 270
    assert slot_at(result, "08:00")[1] == at(12, 30)
    assert starts(result)[-1] == "13:00"


# --- closed days, cut-off and the grid's anchor -----------------------------------------


def test_closed_day_gives_no_slots() -> None:
    result = run(mot(), hours=None)
    assert result.slots == ()
    assert result.unavailable_reason is None


def test_cutoff_drops_early_starts() -> None:
    assert starts(run(mot(), hours=NO_BREAKS, now=at(10, 5)))[0] == "12:30"


def test_start_exactly_at_cutoff_is_allowed() -> None:
    assert starts(run(mot(), hours=NO_BREAKS, now=at(10)))[0] == "12:00"


def test_grid_is_anchored_at_opening_time() -> None:
    result = starts(run(mot(), hours=DayHours(time(8, 15), time(12))))
    assert result[:2] == ["08:15", "08:45"]


def test_two_breaks() -> None:
    hours = DayHours(time(8), time(17, 30), ((time(10), time(10, 30)), (time(15), time(15, 15))))
    result = starts(run(general(30), hours=hours))
    assert "10:00" not in result
    assert "15:00" not in result
    assert "10:30" in result
    assert "15:30" in result


# --- bad input -------------------------------------------------------------------------


def test_empty_services_raise() -> None:
    with pytest.raises(ValueError):
        find_slots(DAY, [], ALL_BAYS, WEEKDAY, [], policy(), NOW)


def test_naive_now_raises() -> None:
    with pytest.raises(ValueError):
        find_slots(DAY, [mot()], ALL_BAYS, WEEKDAY, [], policy(), datetime(2026, 11, 1))
