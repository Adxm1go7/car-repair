"""The database itself must refuse two active reservations that overlap in one bay."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Bay, Reservation
from app.seed import seed


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, 10, hour, minute, tzinfo=UTC)


def bay_id(session: Session, slug: str) -> int:
    return session.scalars(select(Bay.id).where(Bay.slug == slug)).one()


def add(
    session: Session,
    bay: int,
    during: Range[datetime],
    *,
    kind: str = "booking",
    active: bool = True,
) -> None:
    session.add(Reservation(bay_id=bay, kind=kind, during=during, active=active))
    session.flush()


@pytest.fixture
def bays(db_session: Session) -> tuple[int, int]:
    seed(db_session)
    return bay_id(db_session, "bay-1"), bay_id(db_session, "bay-2")


def test_overlapping_active_reservations_in_one_bay_are_rejected(
    db_session: Session, bays: tuple[int, int]
) -> None:
    bay_1, _ = bays
    add(db_session, bay_1, Range(at(9), at(10)))
    with pytest.raises(IntegrityError) as error, db_session.begin_nested():
        add(db_session, bay_1, Range(at(9, 30), at(10, 30)))
    assert getattr(error.value.orig, "sqlstate", None) == "23P01"


def test_same_range_in_different_bays_is_allowed(
    db_session: Session, bays: tuple[int, int]
) -> None:
    bay_1, bay_2 = bays
    add(db_session, bay_1, Range(at(9), at(10)))
    add(db_session, bay_2, Range(at(9), at(10)))


def test_back_to_back_reservations_are_allowed(db_session: Session, bays: tuple[int, int]) -> None:
    bay_1, _ = bays
    add(db_session, bay_1, Range(at(9), at(10)))
    add(db_session, bay_1, Range(at(10), at(11)))


def test_overlap_with_an_inactive_reservation_is_allowed(
    db_session: Session, bays: tuple[int, int]
) -> None:
    bay_1, _ = bays
    add(db_session, bay_1, Range(at(9), at(10)), active=False)
    add(db_session, bay_1, Range(at(9, 30), at(10, 30)))


def test_kind_must_be_booking_or_block(db_session: Session, bays: tuple[int, int]) -> None:
    bay_1, _ = bays
    with pytest.raises(IntegrityError), db_session.begin_nested():
        add(db_session, bay_1, Range(at(9), at(10)), kind="holiday")


def test_empty_range_is_rejected(db_session: Session, bays: tuple[int, int]) -> None:
    bay_1, _ = bays
    with pytest.raises(IntegrityError), db_session.begin_nested():
        add(db_session, bay_1, Range(at(9), at(9)))


def test_unbounded_range_is_rejected(db_session: Session, bays: tuple[int, int]) -> None:
    bay_1, _ = bays
    with pytest.raises(IntegrityError), db_session.begin_nested():
        add(db_session, bay_1, Range(None, at(9)))
