"""Which start times are free for a set of services on one day.

A pure function over plain data: no database, no web framework, no clock. Everything it
needs, including "now", is passed in, so it can be tested exhaustively.
"""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class ServiceInfo:
    id: int
    duration_minutes: int
    bay_type_id: int


@dataclass(frozen=True)
class BayInfo:
    id: int
    bay_type_id: int


@dataclass(frozen=True)
class DayHours:
    """Opening hours for one day, as garage-local wall-clock times."""

    open: time
    close: time
    breaks: tuple[tuple[time, time], ...] = ()


@dataclass(frozen=True)
class Occupied:
    """Time a bay is already taken, half-open [start, end). Aware datetimes."""

    bay_id: int
    start: datetime
    end: datetime


@dataclass(frozen=True)
class Policy:
    zone: ZoneInfo
    grid_minutes: int
    buffer_minutes: int
    cutoff_minutes: int


@dataclass(frozen=True)
class Slot:
    """A free start. `start` and `end` are local; `end` is the real end, without the buffer."""

    start: datetime
    end: datetime
    bay_ids: tuple[int, ...]


@dataclass(frozen=True)
class DayAvailability:
    duration_minutes: int
    slots: tuple[Slot, ...]
    unavailable_reason: Literal["mixed_bay_types"] | None


def find_slots(
    day: date,
    services: Sequence[ServiceInfo],
    bays: Sequence[BayInfo],
    hours: DayHours | None,
    occupied: Sequence[Occupied],
    policy: Policy,
    now: datetime,
) -> DayAvailability:
    """Every start on `day` where one bay is free for the whole job plus its buffer.

    `hours=None` means the garage is closed that day.
    """
    if not services:
        raise ValueError("At least one service is needed")
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")

    duration = sum(service.duration_minutes for service in services)
    bay_types = {service.bay_type_id for service in services}
    if len(bay_types) > 1:
        return DayAvailability(duration, (), "mixed_bay_types")
    if hours is None:
        return DayAvailability(duration, (), None)

    (bay_type,) = bay_types
    bay_ids = sorted(bay.id for bay in bays if bay.bay_type_id == bay_type)
    busy = {
        bay_id: [
            (taken.start.astimezone(UTC), taken.end.astimezone(UTC))
            for taken in occupied
            if taken.bay_id == bay_id
        ]
        for bay_id in bay_ids
    }

    zone = policy.zone
    job = timedelta(minutes=duration)
    buffer = timedelta(minutes=policy.buffer_minutes)
    closing = datetime.combine(day, hours.close, tzinfo=zone).astimezone(UTC)
    earliest = now.astimezone(UTC) + timedelta(minutes=policy.cutoff_minutes)

    slots = []
    for wall in _wall_clock_grid(day, hours, policy.grid_minutes):
        if any(start <= wall.time() < end for start, end in hours.breaks):
            continue
        local = _existing_local_time(wall, zone)
        if local is None:
            continue
        start_utc = local.astimezone(UTC)
        end_utc = start_utc + job  # real elapsed time, even across a clock change
        if end_utc > closing or start_utc < earliest:
            continue
        occupied_until = end_utc + buffer
        free = tuple(
            bay_id
            for bay_id in bay_ids
            if not any(start < occupied_until and start_utc < end for start, end in busy[bay_id])
        )
        if free:
            slots.append(Slot(start=local, end=end_utc.astimezone(zone), bay_ids=free))
    return DayAvailability(duration, tuple(slots), None)


def _wall_clock_grid(day: date, hours: DayHours, grid_minutes: int) -> Iterator[datetime]:
    """Naive local times from opening, every `grid_minutes`, before closing."""
    current = datetime.combine(day, hours.open)
    closing = datetime.combine(day, hours.close)
    step = timedelta(minutes=grid_minutes)
    while current < closing:
        yield current
        current += step


def _existing_local_time(wall: datetime, zone: ZoneInfo) -> datetime | None:
    """`wall` as an aware time in `zone`, or None if the clocks skip it.

    An ambiguous time (clocks going back) takes its first occurrence, fold=0.
    """
    aware = wall.replace(tzinfo=zone)
    round_trip = aware.astimezone(UTC).astimezone(zone)
    if round_trip.replace(tzinfo=None) != wall:
        return None
    return aware
