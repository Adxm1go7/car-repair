"""On the live demo the two shared logins are public, so nobody may lock, reset or change them."""

from collections.abc import Iterator
from datetime import timedelta

import pytest
from conftest import ORIGIN, ClientFor
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.clock import utc_now
from app.config import AppConfig
from app.demo_data import DEMO_STAFF
from app.models import EmailLog, LoginAttempt, StaffUser
from app.seed import seed
from app.staff.demo_accounts import DEMO_ACCOUNT_LOCKED

ADMIN = next(s for s in DEMO_STAFF if s.role == "admin")
STAFF = next(s for s in DEMO_STAFF if s.role == "staff")
TEST_CLIENT_IP = "testclient"  # what Starlette's TestClient reports as the visitor


def client_with(
    client_for: ClientFor, migrated_url: str, *, demo_site: bool
) -> Iterator[TestClient]:
    config = AppConfig(database_url=migrated_url, environment="test", demo_site=demo_site)
    with client_for(config) as client:
        client.headers["Origin"] = ORIGIN
        yield client


@pytest.fixture
def demo_client(
    client_for: ClientFor, migrated_url: str, db_session: Session
) -> Iterator[TestClient]:
    seed(db_session, sample_accounts=True)
    db_session.commit()
    yield from client_with(client_for, migrated_url, demo_site=True)


@pytest.fixture
def plain_client(
    client_for: ClientFor, migrated_url: str, db_session: Session
) -> Iterator[TestClient]:
    seed(db_session, sample_accounts=True)
    db_session.commit()
    yield from client_with(client_for, migrated_url, demo_site=False)


def fail_logins(session: Session, email: str, count: int, ip: str | None = None) -> None:
    """`count` recent failed logins for `email`, each from its own address unless `ip`."""
    now = utc_now() - timedelta(minutes=1)
    for n in range(count):
        session.add(LoginAttempt(email=email, ip=ip or f"10.0.0.{n + 1}", succeeded=False, at=now))
    session.commit()


def log_in(client: TestClient, email: str, password: str) -> int:
    return client.post("/api/staff/login", json={"email": email, "password": password}).status_code


def user(session: Session, email: str) -> StaffUser:
    session.expire_all()
    return session.scalars(select(StaffUser).where(StaffUser.email == email)).one()


def test_demo_login_not_locked_by_wrong_passwords(
    demo_client: TestClient, db_session: Session
) -> None:
    fail_logins(db_session, ADMIN.email, 10)
    assert log_in(demo_client, ADMIN.email, ADMIN.password) == 200


def test_demo_login_still_ip_limited(demo_client: TestClient, db_session: Session) -> None:
    fail_logins(db_session, "someone@example.test", 20, ip=TEST_CLIENT_IP)
    assert log_in(demo_client, ADMIN.email, ADMIN.password) == 401


def test_demo_accounts_lock_as_usual_when_off(
    plain_client: TestClient, db_session: Session
) -> None:
    fail_logins(db_session, ADMIN.email, 10)
    assert log_in(plain_client, ADMIN.email, ADMIN.password) == 401


def test_forgot_password_queues_nothing_for_demo_account(
    demo_client: TestClient, db_session: Session
) -> None:
    response = demo_client.post("/api/staff/forgot-password", json={"email": ADMIN.email})

    assert response.status_code == 202
    assert db_session.scalar(select(func.count()).select_from(EmailLog)) == 0


def test_admin_cannot_change_demo_accounts(demo_client: TestClient, db_session: Session) -> None:
    assert log_in(demo_client, ADMIN.email, ADMIN.password) == 200
    staff = user(db_session, STAFF.email)

    attempts = [
        demo_client.patch(f"/api/staff/team/{staff.id}", json={"role": "admin"}),
        demo_client.patch(f"/api/staff/team/{staff.id}", json={"active": False}),
        demo_client.post(f"/api/staff/team/{staff.id}/reset-password"),
    ]

    for response in attempts:
        assert response.status_code == 409
        assert response.json() == {"detail": DEMO_ACCOUNT_LOCKED}
    after = user(db_session, STAFF.email)
    assert (after.role, after.active) == ("staff", True)
    assert db_session.scalar(select(func.count()).select_from(EmailLog)) == 0


def test_invited_staff_behave_normally(demo_client: TestClient, db_session: Session) -> None:
    assert log_in(demo_client, ADMIN.email, ADMIN.password) == 200
    invited = demo_client.post(
        "/api/staff/team", json={"name": "Nia New", "email": "nia@example.test", "role": "staff"}
    ).json()

    response = demo_client.patch(f"/api/staff/team/{invited['id']}", json={"role": "admin"})

    assert response.status_code == 200
    assert response.json()["role"] == "admin"
