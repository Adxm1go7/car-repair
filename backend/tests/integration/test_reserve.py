"""Loading availability data and reserving a slot, against the seeded demo garage."""

from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.orm import Session

from app.availability.engine import Policy
from app.models import Bay, Reservation, Service, Setting
from app.repositories.availability import (
    SettingsUnavailable,
    day_availability,
    load_booking_window_days,
    load_policy,
)
from app.repositories.reservations import SlotUnavailable, reserve
from app.seed import seed

LONDON = ZoneInfo("Europe/London")
DAY = date(2026, 11, 10)  # a Tuesday in GMT, so local time equals UTC
NOW = datetime(2026, 11, 9, 9, tzinfo=UTC)
DELETE = object()


def local(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, 10, hour, minute, tzinfo=LONDON)


def utc(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, 10, hour, minute, tzinfo=UTC)


def service(session: Session, slug: str) -> Service:
    return session.scalars(select(Service).where(Service.slug == slug)).one()


def bay_id(session: Session, slug: str) -> int:
    return session.scalars(select(Bay.id).where(Bay.slug == slug)).one()


def block(
    session: Session, bay_slug: str, start: datetime, end: datetime, active: bool = True
) -> None:
    session.add(
        Reservation(
            bay_id=bay_id(session, bay_slug), kind="block", during=Range(start, end), active=active
        )
    )
    session.flush()


def active_count(session: Session) -> int:
    statement = select(func.count()).select_from(Reservation).where(Reservation.active.is_(True))
    return session.scalar(statement) or 0


@pytest.fixture
def seeded(db_session: Session) -> Session:
    seed(db_session)
    return db_session


# --- reserve -------------------------------------------------------------------


def test_reserve_mot_stores_range_with_buffer(seeded: Session) -> None:
    result = reserve(seeded, [service(seeded, "mot-test").id], local(9), NOW)
    assert (result.start, result.end) == (local(9), local(10))
    seeded.refresh(result.reservation)
    assert result.reservation.bay_id == bay_id(seeded, "mot-bay")
    assert result.reservation.kind == "booking"
    assert result.reservation.during == Range(utc(9), utc(10, 15))


def test_reserve_next_to_an_existing_booking_succeeds(seeded: Session) -> None:
    mot = [service(seeded, "mot-test").id]
    reserve(seeded, mot, local(9), NOW)
    with pytest.raises(SlotUnavailable):
        reserve(seeded, mot, local(10), NOW)  # would start inside the first one's buffer
    reserve(seeded, mot, local(10, 30), NOW)
    assert active_count(seeded) == 2


def test_reserve_start_not_on_the_grid_is_unavailable(seeded: Session) -> None:
    with pytest.raises(SlotUnavailable):
        reserve(seeded, [service(seeded, "mot-test").id], local(9, 10), NOW)


def test_reserve_taken_single_bay_is_unavailable(seeded: Session) -> None:
    mot = [service(seeded, "mot-test").id]
    reserve(seeded, mot, local(9), NOW)
    with pytest.raises(SlotUnavailable):
        reserve(seeded, mot, local(9), NOW)
    assert active_count(seeded) == 1


def test_reserve_spreads_across_general_bays_then_runs_out(seeded: Session) -> None:
    full_service = [service(seeded, "full-service").id]
    bays = [reserve(seeded, full_service, local(9), NOW).reservation.bay_id for _ in range(3)]
    assert bays == [bay_id(seeded, slug) for slug in ("bay-1", "bay-2", "bay-3")]
    with pytest.raises(SlotUnavailable):
        reserve(seeded, full_service, local(9), NOW)


def test_reserve_falls_back_when_constraint_rejects(
    seeded: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    full_service = service(seeded, "full-service")
    stale = day_availability(seeded, [full_service], DAY, NOW, load_policy(seeded))
    block(seeded, "bay-1", utc(9), utc(12, 15))  # a rival got there after the engine looked
    monkeypatch.setattr("app.repositories.reservations.day_availability", lambda *_: stale)
    result = reserve(seeded, [full_service.id], local(9), NOW)
    assert result.reservation.bay_id == bay_id(seeded, "bay-2")


def test_reserve_raises_slot_unavailable_when_every_bay_rejects(
    seeded: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    full_service = service(seeded, "full-service")
    stale = day_availability(seeded, [full_service], DAY, NOW, load_policy(seeded))
    for slug in ("bay-1", "bay-2", "bay-3"):
        block(seeded, slug, utc(9), utc(12, 15))
    monkeypatch.setattr("app.repositories.reservations.day_availability", lambda *_: stale)
    with pytest.raises(SlotUnavailable):
        reserve(seeded, [full_service.id], local(9), NOW)


def test_inactive_reservations_do_not_block(seeded: Session) -> None:
    block(seeded, "mot-bay", utc(9), utc(10, 15), active=False)
    reserve(seeded, [service(seeded, "mot-test").id], local(9), NOW)


def test_cutoff_override_allows_a_start_inside_the_cutoff(seeded: Session) -> None:
    mot = [service(seeded, "mot-test").id]
    with pytest.raises(SlotUnavailable):
        reserve(seeded, mot, local(9), local(8, 30))
    reserve(seeded, mot, local(9), local(8, 30), cutoff_minutes=0)


def test_unknown_service_raises_value_error(seeded: Session) -> None:
    with pytest.raises(ValueError):
        reserve(seeded, [999_999], local(9), NOW)


def test_naive_start_raises_value_error(seeded: Session) -> None:
    with pytest.raises(ValueError):
        reserve(seeded, [service(seeded, "mot-test").id], datetime(2026, 11, 10, 9), NOW)


# --- settings --------------------------------------------------------------------


def set_setting(session: Session, key: str, value: Any) -> None:
    row = session.get(Setting, key)
    assert row is not None
    if value is DELETE:
        session.delete(row)
    else:
        row.value = value
    session.flush()


def test_load_policy_reads_seeded_settings(seeded: Session) -> None:
    assert load_policy(seeded) == Policy(
        zone=LONDON, grid_minutes=30, buffer_minutes=15, cutoff_minutes=120
    )
    assert load_booking_window_days(seeded) == 60


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("slot_grid_minutes", DELETE),
        ("slot_grid_minutes", 4),
        ("slot_grid_minutes", True),
        ("bay_buffer_minutes", -1),
        ("booking_cutoff_minutes", "soon"),
        ("garage_timezone", "Mars/Base"),
    ],
)
def test_load_policy_rejects_broken_settings(seeded: Session, key: str, value: Any) -> None:
    set_setting(seeded, key, value)
    with pytest.raises(SettingsUnavailable):
        load_policy(seeded)


@pytest.mark.parametrize("value", [DELETE, "lots", -1])
def test_load_booking_window_rejects_broken_setting(seeded: Session, value: Any) -> None:
    set_setting(seeded, "booking_window_days", value)
    with pytest.raises(SettingsUnavailable):
        load_booking_window_days(seeded)
