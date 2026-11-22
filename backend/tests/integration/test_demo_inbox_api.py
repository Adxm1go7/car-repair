"""The Demo inbox API: public, read-only, customer emails only, and only on the demo site."""

from collections.abc import Iterator

import pytest
from conftest import ClientFor
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import AppConfig
from app.models import DemoInboxEmail


@pytest.fixture
def demo_client(client_for: ClientFor, migrated_url: str) -> Iterator[TestClient]:
    config = AppConfig(database_url=migrated_url, environment="test", demo_site=True)
    with client_for(config) as client:
        yield client


def store(
    session: Session, to: str = "ann@example.com", template: str = "confirmation"
) -> DemoInboxEmail:
    email = DemoInboxEmail(
        template=template,
        recipient=to,
        subject=f"{template} for {to}",
        text=f"Hello {to}",
        html=f"<p>Hello {to}</p>",
    )
    session.add(email)
    session.commit()
    return email


def test_inbox_is_404_when_off(api_client: TestClient, db_session: Session) -> None:
    email = store(db_session)
    assert api_client.get("/api/demo-inbox").status_code == 404
    assert api_client.get(f"/api/demo-inbox/{email.id}").status_code == 404


def test_lists_newest_first_and_caps_at_50(demo_client: TestClient, db_session: Session) -> None:
    ids = [store(db_session, to=f"p{n}@example.com").id for n in range(51)]

    listed = demo_client.get("/api/demo-inbox").json()

    assert len(listed) == 50
    assert listed[0]["id"] == max(ids)
    assert set(listed[0]) == {"id", "to", "subject", "sent_at"}


def test_filters_by_recipient(demo_client: TestClient, db_session: Session) -> None:
    ann = store(db_session, to="ann@example.com")
    store(db_session, to="bob@example.com")

    listed = demo_client.get("/api/demo-inbox", params={"to": " Ann@Example.com "}).json()

    assert [email["id"] for email in listed] == [ann.id]


def test_staff_emails_never_shown(demo_client: TestClient, db_session: Session) -> None:
    reset = store(db_session, to="admin@example.test", template="password_reset")
    invite = store(db_session, to="new@example.test", template="staff_invite")

    assert demo_client.get("/api/demo-inbox").json() == []
    for email in (reset, invite):
        response = demo_client.get(f"/api/demo-inbox/{email.id}")
        assert response.status_code == 404
        assert response.json() == {"detail": "No such email"}


def test_reads_one_email(demo_client: TestClient, db_session: Session) -> None:
    email = store(db_session)

    body = demo_client.get(f"/api/demo-inbox/{email.id}").json()

    assert body["to"] == "ann@example.com"
    assert body["text"] == "Hello ann@example.com"
    assert body["html"] == "<p>Hello ann@example.com</p>"


def test_unknown_email_is_404(demo_client: TestClient) -> None:
    assert demo_client.get("/api/demo-inbox/999999").status_code == 404
