"""The booking link for a request and an approval: what it shows, paying, and cancelling."""

import threading
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from alembic import command
from conftest import alembic_config
from factories import make_request, make_staff
from fakes import FakeProvider
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.bookings.links import create_link
from app.bookings.self_service import CancelRefused, cancel_from_link
from app.clock import utc_now
from app.db import make_engine
from app.models import AuditEntry, Booking, EmailLog, Payment, StaffUser
from app.schedule.approvals import approve_booking
from app.schedule.changes import NotAllowed
from app.seed import seed

NOW = datetime(2026, 11, 9, 9, tzinfo=UTC)  # Monday 09:00 in London (GMT)
START = datetime(2026, 11, 16, 9, tzinfo=UTC)


def set_now(client: TestClient, now: datetime) -> None:
    cast(FastAPI, client.app).dependency_overrides[utc_now] = lambda: now


@pytest.fixture
def client(api_client: TestClient, db_session: Session) -> TestClient:
    seed(db_session)
    set_now(api_client, NOW)
    return api_client


def linked(session: Session, status: str, deadline: datetime) -> tuple[Booking, str]:
    booking = make_request(session, START, deadline, status=status)
    token = create_link(session, booking)
    session.commit()  # a savepoint: still undone after the test
    return booking, token


def post(client: TestClient, booking: Booking, action: str, token: str) -> Any:
    return client.post(f"/api/bookings/{booking.reference}/{action}", json={"token": token})


def reload(session: Session, booking: Booking) -> Booking:
    session.expire_all()
    fresh = session.get(Booking, booking.id)
    assert fresh is not None
    return fresh


def test_view_of_a_request_shows_its_deadline(client: TestClient, db_session: Session) -> None:
    booking, token = linked(db_session, "pending_approval", NOW + timedelta(hours=48))
    response = post(client, booking, "view", token)
    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["status"] == "pending_approval"
    assert body["deadline"] == "2026-11-11T09:00:00+00:00"
    assert body["can_cancel"] is True
    assert body["refund_if_cancelled"] is False


def test_view_of_a_confirmed_booking_has_no_deadline(
    client: TestClient, db_session: Session
) -> None:
    booking, token = linked(db_session, "confirmed", NOW)
    assert post(client, booking, "view", token).json()["deadline"] is None


def test_view_of_an_overdue_approval_releases_it(client: TestClient, db_session: Session) -> None:
    booking, token = linked(db_session, "awaiting_deposit", NOW - timedelta(minutes=1))
    body = post(client, booking, "view", token).json()
    assert body["summary"]["status"] == "expired"
    assert body["can_cancel"] is False
    assert not reload(db_session, booking).reservation.active


def test_pay_an_approval_and_view_it_confirmed(
    client: TestClient, db_session: Session, fake_provider: FakeProvider
) -> None:
    booking, token = linked(db_session, "awaiting_deposit", NOW + timedelta(hours=24))
    response = post(client, booking, "pay", token)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["client_secret"] == "cs_fake_1_secret"  # noqa: S105
    assert body["expires_in_seconds"] == 24 * 3600
    assert body["amount_pence"] == 2000
    assert reload(db_session, booking).hold_expires_at == NOW + timedelta(hours=24)

    fake_provider.mark_paid("cs_fake_1")
    view = post(client, booking, "view", token).json()
    assert view["summary"]["status"] == "confirmed"
    assert view["deposit_status"] == "paid"


def test_pay_twice_reuses_the_form(
    client: TestClient, db_session: Session, fake_provider: FakeProvider
) -> None:
    booking, token = linked(db_session, "awaiting_deposit", NOW + timedelta(hours=24))
    post(client, booking, "pay", token)
    post(client, booking, "pay", token)
    assert len(fake_provider.called("start_checkout")) == 1


def test_pay_a_request_not_approved_yet_is_refused(client: TestClient, db_session: Session) -> None:
    booking, token = linked(db_session, "pending_approval", NOW + timedelta(hours=48))
    response = post(client, booking, "pay", token)
    assert response.status_code == 409
    assert response.json()["detail"] == "Nothing to pay"


def test_pay_an_overdue_approval_is_refused(client: TestClient, db_session: Session) -> None:
    booking, token = linked(db_session, "awaiting_deposit", NOW - timedelta(minutes=1))
    assert post(client, booking, "pay", token).status_code == 409
    assert reload(db_session, booking).status == "expired"


def test_pay_with_a_bad_link_is_not_found(client: TestClient, db_session: Session) -> None:
    booking, _ = linked(db_session, "awaiting_deposit", NOW + timedelta(hours=24))
    assert post(client, booking, "pay", "wrong").status_code == 404


def test_cancel_a_request_from_the_link(client: TestClient, db_session: Session) -> None:
    booking, token = linked(db_session, "pending_approval", NOW + timedelta(hours=48))
    response = post(client, booking, "cancel", token)
    assert response.status_code == 200
    assert response.json()["summary"]["status"] == "cancelled"
    assert not reload(db_session, booking).reservation.active
    db_session.expire_all()
    templates = list(db_session.scalars(select(EmailLog.template)))
    assert templates == ["cancellation"]


def test_cancel_an_approval_closes_its_form(
    client: TestClient, db_session: Session, fake_provider: FakeProvider
) -> None:
    booking, token = linked(db_session, "awaiting_deposit", NOW + timedelta(hours=24))
    post(client, booking, "pay", token)
    assert post(client, booking, "cancel", token).status_code == 200
    assert fake_provider.called("close_checkout") == [{"session_ref": "cs_fake_1"}]
    db_session.expire_all()
    deposit = db_session.scalars(select(Payment)).one()
    assert deposit.status == "expired"


def test_approve_and_customer_cancel_at_once_one_wins(fresh_database_url: str) -> None:
    command.upgrade(alembic_config(fresh_database_url), "head")
    engine = make_engine(fresh_database_url)
    try:
        with Session(engine) as session:
            seed(session)
            staff_id = make_staff(session).id
            booking = make_request(session, START, NOW + timedelta(hours=48))
            reference = booking.reference
            token = create_link(session, booking)
            session.commit()
        barrier = threading.Barrier(2)
        outcomes: list[str] = []

        def approve() -> None:
            with Session(engine) as session:
                staff = session.get(StaffUser, staff_id)
                assert staff is not None
                barrier.wait()
                try:
                    approve_booking(session, staff, reference, NOW)
                    session.commit()
                    outcomes.append("approved")
                except NotAllowed:
                    session.rollback()
                    outcomes.append("refused")

        def cancel() -> None:
            with Session(engine) as session:
                barrier.wait()
                try:
                    cancel_from_link(session, FakeProvider(), reference, token, NOW, 24)
                    session.commit()
                    outcomes.append("cancelled")
                except CancelRefused:
                    session.rollback()
                    outcomes.append("refused")

        threads = [threading.Thread(target=approve), threading.Thread(target=cancel)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        # The customer can cancel an approval too, so both may succeed (approve first); if
        # the cancel goes first, the approval is refused. Either way it ends cancelled.
        assert "cancelled" in outcomes
        assert sorted(outcomes) in (["approved", "cancelled"], ["cancelled", "refused"])
        with Session(engine) as session:
            status = session.scalars(
                select(Booking.status).where(Booking.reference == reference)
            ).one()
            approvals = session.scalar(select(func.count()).select_from(AuditEntry))
        assert status == "cancelled"
        assert approvals == (1 if "approved" in outcomes else 0)
    finally:
        engine.dispose()
