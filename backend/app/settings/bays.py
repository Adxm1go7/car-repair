"""Admins' changes to bays and bay types: add, rename, take out of use and put back.

Taking a bay out of use takes the hours-and-bays lock exclusive, then refuses while the bay
has bookings that count ending after now, so a booking made at the same moment is either
seen or sees the bay gone. Each change writes its audit entry in the same transaction.
Nothing here commits.
"""

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.orm import Session, selectinload

from app.models import Bay, BayType, Block, Booking, Reservation, StaffUser
from app.settings.clashes import bookings_in_bay
from app.settings.lock import lock_exclusive
from app.settings.slugs import make_slug
from app.staff.audit import record_audit


class NameTaken(Exception):
    """Another bay (or bay type) already has this name, ignoring case."""


class UnknownBayType(Exception):
    pass


class BayInUse(Exception):
    """The bookings that stop the bay going out of use."""

    def __init__(self, bookings: list[Booking]) -> None:
        super().__init__("clashes")
        self.bookings = bookings


def list_bays(session: Session) -> list[Bay]:
    statement = select(Bay).options(selectinload(Bay.bay_type)).order_by(Bay.id)
    return list(session.scalars(statement))


def list_bay_types(session: Session) -> list[BayType]:
    return list(session.scalars(select(BayType).order_by(BayType.id)))


def _check_bay_name_free(session: Session, name: str, bay_id: int | None = None) -> None:
    statement = select(Bay.id).where(func.lower(Bay.name) == name.lower())
    if bay_id is not None:
        statement = statement.where(Bay.id != bay_id)
    if session.scalars(statement).first() is not None:
        raise NameTaken


def create_bay_type(session: Session, admin: StaffUser, name: str, now: datetime) -> BayType:
    """A new bay type. It can't be renamed later; it does nothing until a bay and a service
    use it."""
    taken = session.scalars(select(BayType.id).where(func.lower(BayType.name) == name.lower()))
    if taken.first() is not None:
        raise NameTaken
    slugs = set(session.scalars(select(BayType.slug)))
    bay_type = BayType(slug=make_slug(name, slugs), name=name)
    session.add(bay_type)
    session.flush()
    record_audit(
        session,
        admin,
        "bay_type.create",
        "bay_type",
        bay_type.id,
        after={"slug": bay_type.slug, "name": bay_type.name},
        now=now,
    )
    return bay_type


def create_bay(
    session: Session, admin: StaffUser, name: str, bay_type_id: int, now: datetime
) -> Bay:
    """A new bay, in use at once, and covered by every all-bays block that hasn't ended."""
    bay_type = session.get(BayType, bay_type_id)
    if bay_type is None:
        raise UnknownBayType
    _check_bay_name_free(session, name)
    slugs = set(session.scalars(select(Bay.slug)))
    bay = Bay(slug=make_slug(name, slugs), name=name, bay_type_id=bay_type.id, active=True)
    session.add(bay)
    session.flush()
    extend_all_bay_blocks(session, bay, now)
    record_audit(
        session,
        admin,
        "bay.create",
        "bay",
        bay.id,
        after={"slug": bay.slug, "name": bay.name, "bay_type": bay_type.name},
        now=now,
    )
    return bay


def update_bay(
    session: Session, admin: StaffUser, bay: Bay, changes: Mapping[str, Any], now: datetime
) -> None:
    """Rename, and/or take out of use or put back. Raises NameTaken, or BayInUse before
    anything is changed. A field sent with its current value writes nothing."""
    active = changes.get("active")
    if active is False:
        lock_exclusive(session)
        session.refresh(bay)  # what it is now, after waiting for the lock
    name: str | None = changes.get("name")
    renaming = name is not None and name != bay.name
    if name is not None and renaming:
        _check_bay_name_free(session, name, bay.id)
    going_out = active is False and bay.active
    if going_out:
        clashes = bookings_in_bay(session, bay.id, now)
        if clashes:
            raise BayInUse(clashes)

    if name is not None and renaming:
        before = bay.name
        bay.name = name
        session.flush()
        record_audit(
            session,
            admin,
            "bay.rename",
            "bay",
            bay.id,
            before={"name": before},
            after={"name": bay.name},
            now=now,
        )
    if active is not None and active != bay.active:
        bay.active = active
        session.flush()
        if active:
            extend_all_bay_blocks(session, bay, now)
        record_audit(
            session,
            admin,
            "bay.back_in_use" if active else "bay.out_of_use",
            "bay",
            bay.id,
            before={"active": not active},
            after={"active": active},
            now=now,
        )


def _free_parts(
    start: datetime, end: datetime, taken: list[tuple[datetime, datetime]]
) -> list[tuple[datetime, datetime]]:
    """[start, end) minus the taken ranges (sorted by start)."""
    parts = []
    cursor = start
    for taken_start, taken_end in taken:
        if taken_end <= cursor or taken_start >= end:
            continue
        if taken_start > cursor:
            parts.append((cursor, taken_start))
        cursor = max(cursor, taken_end)
    if cursor < end:
        parts.append((cursor, end))
    return parts


def extend_all_bay_blocks(session: Session, bay: Bay, now: datetime) -> None:
    """Cover a bay that's just been added or put back by every all-bays block that hasn't
    ended, from now on, skipping the time the bay already has taken (its own blocks, say).

    The blocks are locked, so one being removed at the same moment either goes first (and
    isn't extended) or waits for this."""
    blocks = list(
        session.scalars(
            select(Block)
            .where(Block.all_bays.is_(True), Block.removed_at.is_(None), Block.end_at > now)
            .order_by(Block.start_at, Block.id)
            .with_for_update()
        )
    )
    if not blocks:
        return
    taken = []
    for reservation in session.scalars(
        select(Reservation).where(
            Reservation.bay_id == bay.id,
            Reservation.active.is_(True),
            Reservation.during.overlaps(Range(now, max(block.end_at for block in blocks))),
        )
    ):
        during = reservation.during
        assert during.lower is not None and during.upper is not None  # noqa: S101 - bounded
        taken.append((during.lower, during.upper))
    taken.sort()
    for block in blocks:
        for start, end in _free_parts(max(block.start_at, now), block.end_at, taken):
            session.add(
                Reservation(
                    bay_id=bay.id, kind="block", block_id=block.id, during=Range(start, end)
                )
            )
    session.flush()
