"""Blocked time: a holiday, a broken lift. One bay or every bay, refused while it would
cover any booking (or another block), so staff deal with those customers first.

Nothing here commits.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, selectinload

from app.models import Bay, Block, Booking, Reservation, StaffUser
from app.repositories.bookings import expired_hold, release_expired_holds
from app.repositories.reservations import DEADLOCK_DETECTED, EXCLUSION_VIOLATION
from app.staff.audit import record_audit


class BlockClashes(Exception):
    """What's in the way: the bookings and blocks the new block would cover."""

    def __init__(self, bookings: list[tuple[Booking, Bay]], blocks: list[Block]) -> None:
        super().__init__("clashes")
        self.bookings = bookings
        self.blocks = blocks


class UnknownBay(Exception):
    pass


def _bays(session: Session, bay_id: int | None) -> list[Bay]:
    statement = select(Bay).where(Bay.active.is_(True)).order_by(Bay.id)
    if bay_id is not None:
        statement = statement.where(Bay.id == bay_id)
    bays = list(session.scalars(statement))
    if not bays:
        raise UnknownBay
    return bays


def _clashes(
    session: Session, bays: Sequence[Bay], start: datetime, end: datetime, now: datetime
) -> BlockClashes | None:
    by_id = {bay.id: bay for bay in bays}
    rows = session.execute(
        select(Reservation, Booking)
        .outerjoin(Booking, Booking.reservation_id == Reservation.id)
        .options(selectinload(Reservation.block))
        .where(
            Reservation.bay_id.in_(by_id),
            Reservation.active.is_(True),
            Reservation.during.overlaps(Range(start, end)),
            or_(Booking.id.is_(None), ~expired_hold(now)),
        )
        .order_by(Reservation.during)
    ).all()
    bookings = [(b, by_id[r.bay_id]) for r, b in rows if b is not None]
    blocks: list[Block] = []
    for reservation, booking in rows:
        if booking is None and reservation.block is not None and reservation.block not in blocks:
            blocks.append(reservation.block)
    return BlockClashes(bookings, blocks) if bookings or blocks else None


def _snapshot(block: Block, bays: Sequence[Bay]) -> dict[str, Any]:
    return {
        "bays": [bay.name for bay in bays],
        "start": block.start_at.isoformat(),
        "end": block.end_at.isoformat(),
        "note": block.note,
    }


def create_block(
    session: Session,
    staff: StaffUser,
    bay_id: int | None,
    start: datetime,
    end: datetime,
    note: str,
    now: datetime,
) -> Block:
    """Block `[start, end)` on one bay, or every active bay when `bay_id` is None. Raises
    BlockClashes or UnknownBay. A booking's buffer counts: a block can't start in it."""
    bays = _bays(session, bay_id)
    release_expired_holds(session, now)  # a hold past its time is no longer in the way
    clashes = _clashes(session, bays, start, end, now)
    if clashes is not None:
        raise clashes
    block = Block(
        note=note, start_at=start, end_at=end, all_bays=bay_id is None, created_by=staff.id
    )
    try:
        with session.begin_nested():
            session.add(block)
            session.flush()
            for bay in bays:
                session.add(
                    Reservation(
                        bay_id=bay.id, kind="block", block_id=block.id, during=Range(start, end)
                    )
                )
            session.flush()
    except (IntegrityError, OperationalError) as error:
        if getattr(error.orig, "sqlstate", None) not in (EXCLUSION_VIOLATION, DEADLOCK_DETECTED):
            raise
        # Something was booked since we looked. Say what.
        raced = _clashes(session, bays, start, end, now)
        raise (raced or BlockClashes([], [])) from error
    record_audit(
        session, staff, "block.create", "block", block.id, after=_snapshot(block, bays), now=now
    )
    return block


def remove_block(session: Session, staff: StaffUser, block_id: int, now: datetime) -> None:
    """Free the blocked time. Raises LookupError if there's no such block, or it's gone."""
    block = session.scalars(
        select(Block)
        .where(Block.id == block_id, Block.removed_at.is_(None))
        .options(selectinload(Block.reservations).selectinload(Reservation.bay))
        .with_for_update()
    ).one_or_none()
    if block is None:
        raise LookupError(block_id)
    bays = sorted((r.bay for r in block.reservations), key=lambda bay: bay.id)
    block.removed_at = now
    for reservation in block.reservations:
        reservation.active = False
    session.flush()
    record_audit(
        session, staff, "block.remove", "block", block.id, before=_snapshot(block, bays), now=now
    )
