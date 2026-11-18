"""The free times staff see: the same engine as customers, without the cut-off or window."""

from datetime import UTC, date, datetime, timedelta

import pytest
from factories import first_day, make_block_reservation, make_hold
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Bay, BookingItem, Service
from app.schedule.availability import (
    infos_for_booking,
    infos_for_services,
    staff_free_times,
    staff_policy,
)
from app.seed import seed

DAY = date(2026, 11, 10)  # a Tuesday in GMT: local time is UTC
NOW = datetime(2026, 11, 10, 9, tzinfo=UTC)


@pytest.fixture
def seeded(db_session: Session) -> Session:
    seed(db_session)
    return db_session


def service(session: Session, slug: str) -> Service:
    return session.scalars(select(Service).where(Service.slug == slug)).one()


def starts(session: Session, slug: str, day: date = DAY, **kwargs: int) -> list[str]:
    infos = infos_for_services([service(session, slug)])
    result = staff_free_times(session, infos, day, NOW, **kwargs)
    return [slot.start.strftime("%H:%M") for slot in result.slots]


def utc(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, 10, hour, minute, tzinfo=UTC)


def test_staff_policy_has_no_cutoff(seeded: Session) -> None:
    assert staff_policy(seeded).cutoff_minutes == 0


def test_staff_can_book_inside_the_cutoff(seeded: Session) -> None:
    found = starts(seeded, "mot-test")
    assert found[:2] == ["09:00", "09:30"]  # customers couldn't book before 11:00


def test_staff_times_ignore_the_booking_window(seeded: Session) -> None:
    assert starts(seeded, "mot-test", DAY + timedelta(days=91))  # 13 weeks on: a Tuesday


def test_moving_ignores_its_own_reservation(seeded: Session) -> None:
    booking = make_hold(seeded, utc(10), NOW, status="confirmed")
    assert "10:30" not in starts(seeded, "mot-test")
    found = starts(seeded, "mot-test", exclude_reservation_id=booking.reservation_id)
    assert {"10:00", "10:30"} <= set(found)


def test_booking_durations_come_from_items(seeded: Session) -> None:
    mot = service(seeded, "mot-test")
    booking = make_hold(seeded, utc(9), NOW, status="confirmed")
    booking.items = [
        BookingItem(
            service_id=mot.id,
            service_name=mot.name,
            price_from_pence=mot.price_from_pence,
            price_to_pence=mot.price_to_pence,
            duration_minutes=30,  # the MOT took 30 minutes when this was booked
            position=0,
        )
    ]
    seeded.flush()
    infos = infos_for_booking(booking)
    assert [(i.id, i.duration_minutes) for i in infos] == [(mot.id, 30)]
    result = staff_free_times(
        seeded, infos, DAY, NOW, exclude_reservation_id=booking.reservation_id
    )
    assert result.slots[-1].start.strftime("%H:%M") == "17:00"
    assert starts(seeded, "mot-test")[-1] == "16:30"  # the service's own 60 minutes


def test_blocks_and_breaks_still_apply(seeded: Session) -> None:
    mot_bay = seeded.scalars(select(Bay.id).where(Bay.slug == "mot-bay")).one()
    make_block_reservation(seeded, mot_bay, utc(14), utc(15))
    found = starts(seeded, "mot-test")
    assert "14:00" not in found
    assert "12:30" not in found  # lunch
    assert "15:00" in found


def test_closed_day_has_no_times(seeded: Session) -> None:
    # Sunday is open 10:00-13:00 in the demo; close it.
    sunday = first_day(seeded, 6)
    assert sunday is not None
    sunday.open_time = sunday.close_time = None
    seeded.flush()
    assert starts(seeded, "mot-test", date(2026, 11, 15)) == []
