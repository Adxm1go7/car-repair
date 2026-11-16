"""Staff open a booking, move it, cancel it as the garage, and move the job through its status."""

import threading
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from alembic import command
from conftest import alembic_config
from factories import make_deposit, make_hold, make_staff
from fakes import FakeProvider
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.orm import Session

from app.bookings.links import create_link
from app.bookings.rules import customer_can_cancel
from app.clock import utc_now
from app.db import make_engine
from app.models import (
    AuditEntry,
    Bay,
    Booking,
    BookingItem,
    BookingLink,
    EmailLog,
    Service,
    StaffUser,
)
from app.schedule.changes import NotAllowed, change_status
from app.seed import seed

NOW = datetime(2026, 11, 9, 9, tzinfo=UTC)  # Monday 09:00
START = datetime(2026, 11, 10, 9, tzinfo=UTC)  # Tuesday 09:00


def utc(hour: int, minute: int = 0, day: int = 10) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=UTC)


def bay(session: Session, slug: str) -> int:
    return session.scalars(select(Bay.id).where(Bay.slug == slug)).one()


def paid_mot(session: Session, start: datetime = START) -> Booking:
    """A confirmed one-hour MOT with its service item and a paid deposit."""
    booking = make_hold(session, start, NOW, status="confirmed")
    mot = session.scalars(select(Service).where(Service.slug == "mot-test")).one()
    booking.items = [
        BookingItem(
            service_id=mot.id,
            service_name=mot.name,
            price_from_pence=mot.price_from_pence,
            price_to_pence=mot.price_to_pence,
            duration_minutes=60,
            position=0,
        )
    ]
    booking.confirmed_at = NOW - timedelta(days=5)
    deposit = make_deposit(session, booking, ref=f"cs_{booking.reference}", status="paid")
    deposit.payment_intent_ref = f"pi_{booking.reference}"
    session.flush()
    return booking


@pytest.fixture
def client(staff_client: TestClient, db_session: Session) -> TestClient:
    seed(db_session)
    staff_client.app.dependency_overrides[utc_now] = lambda: NOW  # type: ignore[attr-defined]
    return staff_client


def at(client: TestClient, when: datetime) -> None:
    client.app.dependency_overrides[utc_now] = lambda: when  # type: ignore[attr-defined]


def detail(client: TestClient, reference: str) -> dict[str, Any]:
    response = client.get(f"/api/staff/bookings/{reference}")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def move(client: TestClient, booking: Booking, start: datetime, bay_id: int, **extra: Any) -> Any:
    return client.post(
        f"/api/staff/bookings/{booking.reference}/move",
        json={"start": start.isoformat(), "bay_id": bay_id, **extra},
    )


def emails(session: Session) -> list[tuple[str, str]]:
    rows = session.scalars(select(EmailLog).order_by(EmailLog.id))
    return [(row.template, row.status) for row in rows]


def actions(session: Session) -> list[str]:
    return list(session.scalars(select(AuditEntry.action).order_by(AuditEntry.id)))


# --- detail --------------------------------------------------------------------


def test_detail_shows_the_booking_and_its_actions(client: TestClient, db_session: Session) -> None:
    booking = paid_mot(db_session)
    body = detail(client, booking.reference)
    assert body["reference"] == booking.reference
    assert body["status"] == "confirmed"
    assert body["source"] == "online"
    assert body["start"] == "2026-11-10T09:00:00+00:00"
    assert body["bay"] == {"id": bay(db_session, "mot-bay"), "name": "MOT bay"}
    assert body["services"] == ["MOT test"]
    assert body["customer_phone"] == "07700 900123"
    assert body["deposit_status"] == "paid"
    assert body["actions"] == ["start", "move", "cancel"]
    assert body["starts_on_another_day"] is True
    assert body["history"] == [{"at": "2026-11-04T09:00:00+00:00", "text": "Booked online"}]


def test_detail_unknown_reference_is_404(client: TestClient) -> None:
    assert client.get("/api/staff/bookings/ZZZZ-ZZZZ").status_code == 404
    assert client.get("/api/staff/bookings/" + "x" * 50).status_code == 404


# --- move ----------------------------------------------------------------------


def test_move_updates_booking_reservation_links_and_audits(
    client: TestClient, db_session: Session
) -> None:
    booking = paid_mot(db_session)
    create_link(db_session, booking)
    response = move(client, booking, utc(14), bay(db_session, "mot-bay"), reason="Lift broken")
    assert response.status_code == 200, response.text
    db_session.expire_all()
    assert (booking.start_at, booking.end_at) == (utc(14), utc(15))
    assert booking.reservation.during == Range(utc(14), utc(15, 15))
    link = db_session.scalars(select(BookingLink)).one()
    assert link.expires_at == utc(15) + timedelta(days=7)
    assert actions(db_session) == ["booking.move"]
    entry = db_session.scalars(select(AuditEntry)).one()
    assert entry.reason == "Lift broken"
    assert entry.before == {
        "start": START.isoformat(),
        "end": utc(10).isoformat(),
        "bay": "MOT bay",
    }
    email = db_session.scalars(select(EmailLog)).one()
    assert email.template == "moved"
    assert email.context == {
        "reason": "Lift broken",
        "previous_start": START.isoformat(),
        "previous_end": utc(10).isoformat(),
        "previous_bay": "MOT bay",
    }
    assert response.json()["start"] == "2026-11-10T14:00:00+00:00"


def test_move_into_a_taken_time_is_409_and_changes_nothing(
    client: TestClient, db_session: Session
) -> None:
    booking = paid_mot(db_session)
    paid_mot(db_session, utc(14))
    response = move(client, booking, utc(14), bay(db_session, "mot-bay"))
    assert response.status_code == 409
    assert response.json() == {"detail": "taken"}
    db_session.expire_all()
    assert booking.start_at == START
    assert actions(db_session) == []
    assert emails(db_session) == []


def test_move_later_same_morning_overlapping_itself(
    client: TestClient, db_session: Session
) -> None:
    booking = paid_mot(db_session)
    assert move(client, booking, utc(9, 30), bay(db_session, "mot-bay")).status_code == 200


def test_move_to_another_day_and_inside_the_cutoff(client: TestClient, db_session: Session) -> None:
    booking = paid_mot(db_session)
    assert move(client, booking, utc(9, 30, day=9), bay(db_session, "mot-bay")).status_code == 200


def test_move_same_time_and_bay_is_no_change(client: TestClient, db_session: Session) -> None:
    booking = paid_mot(db_session)
    response = move(client, booking, START, bay(db_session, "mot-bay"))
    assert response.status_code == 409
    assert response.json() == {"detail": "no_change"}


def test_move_into_a_bay_of_the_wrong_type_is_taken(
    client: TestClient, db_session: Session
) -> None:
    booking = paid_mot(db_session)
    assert move(client, booking, utc(14), bay(db_session, "bay-1")).json() == {"detail": "taken"}


def test_move_of_in_progress_booking_is_409(client: TestClient, db_session: Session) -> None:
    booking = paid_mot(db_session)
    booking.status = "in_progress"
    db_session.flush()
    response = move(client, booking, utc(14), bay(db_session, "mot-bay"))
    assert response.status_code == 409
    assert response.json() == {"detail": "not_allowed"}


def test_move_drops_a_reminder_that_hasnt_gone_out(client: TestClient, db_session: Session) -> None:
    booking = paid_mot(db_session)
    db_session.add(EmailLog(template="reminder", booking=booking, recipient="sam@example.com"))
    db_session.flush()
    move(client, booking, utc(14), bay(db_session, "mot-bay"))
    assert emails(db_session) == [("moved", "queued")]


def test_customer_cancel_after_move_uses_new_start(client: TestClient, db_session: Session) -> None:
    booking = paid_mot(db_session, utc(14, day=12))  # Thursday: free to cancel until Wednesday
    assert customer_can_cancel("confirmed", booking.start_at, NOW, 24)
    # Moved to Tuesday 08:30, 23.5 hours from now: inside the free-cancellation period.
    assert move(client, booking, utc(8, 30), bay(db_session, "mot-bay")).status_code == 200
    db_session.expire_all()
    assert not customer_can_cancel(booking.status, booking.start_at, NOW, 24)


# --- garage cancel ---------------------------------------------------------------


def test_garage_cancel_refunds_audits_and_emails(
    client: TestClient, db_session: Session, fake_provider: FakeProvider
) -> None:
    booking = paid_mot(db_session)
    db_session.add(EmailLog(template="reminder", booking=booking, recipient="sam@example.com"))
    db_session.flush()
    response = client.post(
        f"/api/staff/bookings/{booking.reference}/cancel", json={"reason": "  Staff off sick "}
    )
    assert response.status_code == 200, response.text
    db_session.expire_all()
    assert (booking.status, booking.deposit_status) == ("cancelled", "refund_pending")
    assert not booking.reservation.active
    assert len(fake_provider.called("refund")) == 1
    assert actions(db_session) == ["booking.cancel"]
    assert db_session.scalars(select(AuditEntry.reason)).one() == "Staff off sick"
    assert [t for t, _ in emails(db_session)] == ["reminder", "garage_cancellation"]
    assert response.json()["actions"] == []


def test_garage_cancel_with_stripe_down_changes_nothing(
    client: TestClient, db_session: Session, fake_provider: FakeProvider
) -> None:
    booking = paid_mot(db_session)
    fake_provider.fail = True
    response = client.post(f"/api/staff/bookings/{booking.reference}/cancel", json={})
    assert response.status_code == 503
    assert response.json() == {"detail": "We couldn't cancel just now"}
    db_session.expire_all()
    assert booking.status == "confirmed"
    assert actions(db_session) == []
    assert emails(db_session) == []


def test_garage_cancel_twice_is_409(client: TestClient, db_session: Session) -> None:
    booking = paid_mot(db_session)
    client.post(f"/api/staff/bookings/{booking.reference}/cancel", json={})
    response = client.post(f"/api/staff/bookings/{booking.reference}/cancel", json={})
    assert response.status_code == 409


def test_reason_over_500_is_422(client: TestClient, db_session: Session) -> None:
    booking = paid_mot(db_session)
    response = client.post(
        f"/api/staff/bookings/{booking.reference}/cancel", json={"reason": "x" * 501}
    )
    assert response.status_code == 422


# --- status --------------------------------------------------------------------


def status(client: TestClient, booking: Booking, action: str) -> Any:
    return client.post(f"/api/staff/bookings/{booking.reference}/status", json={"action": action})


def test_status_start_complete_and_undo(client: TestClient, db_session: Session) -> None:
    booking = paid_mot(db_session)
    assert status(client, booking, "start").json()["status"] == "in_progress"
    assert status(client, booking, "complete").json()["status"] == "completed"
    body = status(client, booking, "undo_complete").json()
    assert body["status"] == "in_progress"
    assert body["actions"] == ["complete", "undo_start"]
    assert actions(db_session) == ["booking.status"] * 3
    entry = db_session.scalars(select(AuditEntry).order_by(AuditEntry.id.desc())).first()
    assert entry is not None
    assert (entry.before, entry.after) == ({"status": "completed"}, {"status": "in_progress"})


def test_no_show_before_start_is_409(client: TestClient, db_session: Session) -> None:
    booking = paid_mot(db_session)
    response = status(client, booking, "no_show")
    assert response.status_code == 409
    assert response.json() == {"detail": "not_allowed"}


def test_no_show_keeps_deposit_and_reservation(
    client: TestClient, db_session: Session, fake_provider: FakeProvider
) -> None:
    booking = paid_mot(db_session)
    at(client, START + timedelta(minutes=20))
    assert status(client, booking, "no_show").status_code == 200
    db_session.expire_all()
    assert (booking.status, booking.deposit_status) == ("no_show", "paid")
    assert booking.reservation.active
    assert fake_provider.calls == []
    assert emails(db_session) == []


def test_unknown_action_is_422(client: TestClient, db_session: Session) -> None:
    booking = paid_mot(db_session)
    assert status(client, booking, "move").status_code == 422


def test_history_names_the_staff_member_and_reason(client: TestClient, db_session: Session) -> None:
    booking = paid_mot(db_session)
    move(client, booking, utc(14), bay(db_session, "mot-bay"), reason="Lift broken")
    status(client, booking, "start")
    texts = [h["text"] for h in detail(client, booking.reference)["history"]]
    assert texts == [
        "Booked online",
        'Moved from Tue 10 Nov 09:00 by Sam Staff — "Lift broken"',
        "Started the job by Sam Staff",
    ]


# --- two staff at once ---------------------------------------------------------


def test_two_starts_at_once_one_wins(fresh_database_url: str) -> None:
    command.upgrade(alembic_config(fresh_database_url), "head")
    engine = make_engine(fresh_database_url)
    try:
        with Session(engine) as session:
            seed(session)
            staff_id = make_staff(session).id
            reference = paid_mot(session).reference
            session.commit()
        barrier = threading.Barrier(2)
        outcomes: list[str] = []

        def press() -> None:
            with Session(engine) as session:
                staff = session.get(StaffUser, staff_id)
                assert staff is not None
                barrier.wait()
                try:
                    change_status(session, staff, reference, "start", NOW)
                    session.commit()
                    outcomes.append("started")
                except NotAllowed:
                    session.rollback()
                    outcomes.append("refused")

        threads = [threading.Thread(target=press) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert sorted(outcomes) == ["refused", "started"]
        with Session(engine) as session:
            count = select(func.count()).select_from(AuditEntry)
            assert session.scalar(count) == 1
    finally:
        engine.dispose()
