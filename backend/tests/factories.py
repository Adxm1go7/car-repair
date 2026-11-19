"""Test data builders shared by several test files."""

from collections.abc import Mapping, Sequence
from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.orm import Session

from app.bookings.rules import hash_token, new_reference
from app.models import (
    Bay,
    Block,
    Booking,
    BookingItem,
    Enquiry,
    OpeningHours,
    OpeningHoursBreak,
    Payment,
    Reservation,
    Service,
    StaffUser,
    Timetable,
)
from app.models.catalogue import FIRST_TIMETABLE_STARTS
from app.staff.passwords import hash_password

TEST_TOKEN = "t"  # noqa: S105 - a test hold token, not a password
BUFFER = timedelta(minutes=15)
CUSTOMER = {
    "customer_name": "Sam Driver",
    "customer_phone": "07700 900123",
    "customer_email": "sam@example.com",
    "car_registration": "AB12CDE",
    "car_make": "Ford",
    "car_model": "Focus",
}


def make_hold(
    session: Session,
    start: datetime,
    expires_at: datetime,
    *,
    bay_slug: str = "mot-bay",
    status: str = "held",
    details: bool = False,
) -> Booking:
    """A one-hour booking at `start` (aware, any zone) with its reservation, flushed.

    Its token is TEST_TOKEN. A "confirmed" booking gets customer details and a paid deposit,
    so it's valid. A request or an approval (pending_approval, awaiting_deposit) gets
    customer details too. `details=True` gives any booking them, as if payment had started.
    """
    bay = session.scalars(select(Bay.id).where(Bay.slug == bay_slug)).one()
    end = start + timedelta(hours=1)
    reservation = Reservation(
        bay_id=bay,
        kind="booking",
        during=Range(start, end + BUFFER),
        active=status in ("held", "pending_approval", "awaiting_deposit", "confirmed"),
    )
    session.add(reservation)
    session.flush()
    booking = Booking(
        reference=new_reference(),
        reservation_id=reservation.id,
        status=status,
        start_at=start,
        end_at=end,
        hold_expires_at=expires_at,
        hold_token_hash=hash_token(TEST_TOKEN),
        **(CUSTOMER if status != "held" or details else {}),
        deposit_status="paid" if status == "confirmed" else "unpaid",
    )
    session.add(booking)
    session.flush()
    return booking


def make_request(
    session: Session,
    start: datetime,
    deadline: datetime,
    *,
    status: str = "pending_approval",
    bay_slug: str = "bay-1",
) -> Booking:
    """A one-hour diagnostic check (needs approval) waiting for staff, or with status
    "awaiting_deposit" for its deposit, with customer details. Flushed."""
    booking = make_hold(session, start, deadline, bay_slug=bay_slug, status=status)
    check = session.scalars(select(Service).where(Service.slug == "diagnostic-check")).one()
    booking.items = [
        BookingItem(
            service_id=check.id,
            service_name=check.name,
            price_from_pence=check.price_from_pence,
            price_to_pence=check.price_to_pence,
            duration_minutes=60,
            position=0,
        )
    ]
    session.flush()
    return booking


def make_deposit(
    session: Session,
    booking: Booking,
    *,
    ref: str = "cs_test_1",
    status: str = "open",
    amount_pence: int = 2000,
    provider: str = "stripe",
) -> Payment:
    """A deposit payment row for `booking`, flushed."""
    payment = Payment(
        booking_id=booking.id,
        kind="deposit",
        provider=provider,
        provider_ref=ref,
        amount_pence=amount_pence,
        status=status,
    )
    session.add(payment)
    session.flush()
    return payment


BLOCKER_EMAIL = "blocker@example.test"


def make_block_reservation(
    session: Session, bay_id: int, start: datetime, end: datetime, *, active: bool = True
) -> Reservation:
    """A block on one bay from `start` to `end`, with its reservation, flushed. The block is
    made by a staff user created on first use."""
    creator = session.scalars(select(StaffUser).where(StaffUser.email == BLOCKER_EMAIL)).first()
    if creator is None:
        creator = StaffUser(name="Block Maker", email=BLOCKER_EMAIL, role="staff")
        session.add(creator)
        session.flush()
    block = Block(start_at=start, end_at=end, note="Blocked", created_by=creator.id)
    session.add(block)
    session.flush()
    reservation = Reservation(
        bay_id=bay_id, kind="block", block_id=block.id, during=Range(start, end), active=active
    )
    session.add(reservation)
    session.flush()
    return reservation


def make_staff(
    session: Session,
    *,
    role: str = "staff",
    email: str = "sam.staff@example.com",
    password: str | None = "correct horse",  # noqa: S107 - a test password
    active: bool = True,
    name: str = "Sam Staff",
) -> StaffUser:
    """A staff account, flushed. `password=None` leaves it waiting for a set-password link."""
    user = StaffUser(
        name=name,
        email=email,
        role=role,
        active=active,
        password_hash=hash_password(password) if password is not None else None,
    )
    session.add(user)
    session.flush()
    return user


def make_enquiry(
    session: Session,
    *,
    status: str = "new",
    created_at: datetime | None = None,
    handled_at: datetime | None = None,
    description: str = "Rattle from the front left when braking",
    name: str = "Sam Driver",
    reason: str | None = None,
) -> Enquiry:
    """An enquiry, flushed. A handled one (converted or declined) is handled by "Sam Staff",
    made if needed; a converted one gets a confirmed, no-deposit booking from an enquiry."""
    enquiry = Enquiry(
        status=status,
        customer_name=name,
        customer_phone=CUSTOMER["customer_phone"],
        customer_email=CUSTOMER["customer_email"],
        car_registration=CUSTOMER["car_registration"],
        car_make=CUSTOMER["car_make"],
        car_model=CUSTOMER["car_model"],
        description=description,
        decline_reason=reason,
    )
    if created_at is not None:
        enquiry.created_at = created_at
    if status != "new":
        staff = session.scalars(
            select(StaffUser).where(StaffUser.email == "sam.staff@example.com")
        ).one_or_none() or make_staff(session)
        enquiry.handled_by = staff.id
        enquiry.handled_at = handled_at or created_at or datetime.now().astimezone()
    if status == "converted":
        start = (created_at or datetime.now().astimezone()) + timedelta(days=3)
        booking = make_hold(session, start, start, status="confirmed")
        booking.source = "enquiry"
        booking.deposit_status = "not_required"
        enquiry.booking_id = booking.id
    session.add(enquiry)
    session.flush()
    return enquiry


def make_timetable(
    session: Session,
    starts_on: date,
    days: Mapping[int, tuple[time, time] | None],
    breaks: Mapping[int, Sequence[tuple[time, time]]] | None = None,
) -> Timetable:
    """A timetable from `starts_on`, with a row for each weekday in `days` (None = closed)."""
    timetable = Timetable(starts_on=starts_on)
    session.add(timetable)
    session.flush()
    for weekday, hours in days.items():
        session.add(
            OpeningHours(
                timetable_id=timetable.id,
                weekday=weekday,
                open_time=hours[0] if hours else None,
                close_time=hours[1] if hours else None,
            )
        )
    session.flush()
    for weekday, spans in (breaks or {}).items():
        for start, end in spans:
            session.add(
                OpeningHoursBreak(
                    timetable_id=timetable.id, weekday=weekday, start_time=start, end_time=end
                )
            )
    session.flush()
    return timetable


def first_day(session: Session, weekday: int) -> OpeningHours:
    """The first timetable's (the seed's) row for `weekday`."""
    row = session.scalars(
        select(OpeningHours)
        .join(Timetable)
        .where(Timetable.starts_on == FIRST_TIMETABLE_STARTS, OpeningHours.weekday == weekday)
    ).one()
    return row
