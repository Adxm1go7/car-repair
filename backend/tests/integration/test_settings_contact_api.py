"""Admins edit the garage's contact details; the site and every email sent afterwards follow."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from factories import make_deposit, make_hold
from fakes import FakeSender
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.demo_data import DEMO_GARAGE_CONTACT
from app.email.outbox import send_due_emails
from app.email.queue import queue_email
from app.models import AuditEntry, Setting
from app.seed import seed

URL = "/api/staff/settings/contact"
NEW = {
    "name": "Hillside Motors Ltd",
    "address": "14 Station Road, Anytown, AT1 2CD",
    "phone": "01632 960999",
    "email": "hello@example.com",
}


@pytest.fixture
def client(admin_client: TestClient, db_session: Session) -> TestClient:
    seed(db_session)
    return admin_client


def test_read_contact(client: TestClient) -> None:
    response = client.get(URL)
    assert response.status_code == 200
    assert response.json() == DEMO_GARAGE_CONTACT


def test_save_contact_shows_on_public_garage(client: TestClient) -> None:
    messy = NEW | {"name": "  Hillside Motors Ltd ", "email": " Hello@Example.com "}
    response = client.put(URL, json=messy)
    assert response.status_code == 200
    assert response.json() == NEW
    garage = client.get("/api/garage").json()
    assert {key: garage[key] for key in NEW} == NEW
    assert client.get(URL).json() == NEW


@pytest.mark.parametrize(
    "change",
    [
        {"email": "not an email"},
        {"address": "  "},
        {"name": ""},
        {"name": "x" * 101},
        {"address": "x" * 201},
        {"phone": "call us"},
        {"phone": None},
    ],
)
def test_bad_email_or_blank_address_is_422(
    client: TestClient, db_session: Session, change: dict[str, Any]
) -> None:
    assert client.put(URL, json=NEW | change).status_code == 422
    assert client.get(URL).json() == DEMO_GARAGE_CONTACT
    assert db_session.scalars(select(AuditEntry)).first() is None


def test_missing_or_extra_fields_are_422(client: TestClient) -> None:
    without_phone = {key: value for key, value in NEW.items() if key != "phone"}
    assert client.put(URL, json=without_phone).status_code == 422
    assert client.put(URL, json=NEW | {"timezone": "Europe/Paris"}).status_code == 422


def test_queued_email_sent_after_change_uses_new_details(
    client: TestClient, db_session: Session
) -> None:
    now = datetime(2026, 11, 9, 9, tzinfo=UTC)
    booking = make_hold(
        db_session,
        datetime(2026, 11, 20, 9, tzinfo=UTC),
        now + timedelta(minutes=10),
        status="confirmed",
    )
    make_deposit(db_session, booking, ref=f"cs_{booking.reference}", status="paid")
    email = queue_email(db_session, "confirmation", booking)
    assert email is not None
    email.next_attempt_at = now
    db_session.commit()

    assert client.put(URL, json=NEW).status_code == 200
    sender = FakeSender()
    assert send_due_emails(db_session, sender, now, "http://localhost:8080") == 1
    text = sender.sent[0].text
    assert "01632 960999" in text and "hello@example.com" in text
    assert "01632 960123" not in text


def test_contact_change_is_audited(client: TestClient, db_session: Session) -> None:
    client.put(URL, json=NEW)
    client.put(URL, json=NEW)  # the same again: no change, no entry
    entries = list(db_session.scalars(select(AuditEntry)))
    assert len(entries) == 1
    entry = entries[0]
    assert (entry.action, entry.entity_type, entry.entity_id) == ("contact.update", "setting", 0)
    assert (entry.before, entry.after) == (DEMO_GARAGE_CONTACT, NEW)
    stored = db_session.get(Setting, "garage_contact")
    assert stored is not None and stored.value == NEW
