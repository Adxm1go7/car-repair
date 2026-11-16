"""Set-password links: sent by the worker, used once, expiring; forgot password; the first admin."""

import re
from collections.abc import Iterator
from datetime import timedelta

import pytest
from alembic import command
from conftest import ORIGIN, STAFF_PASSWORD, alembic_config
from factories import make_staff
from fakes import FakeSender
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import create_admin
from app.clock import utc_now
from app.config import AppConfig, get_config
from app.db import make_engine
from app.email.outbox import send_due_emails
from app.main import create_app
from app.models import AuditEntry, EmailLog, PasswordToken, StaffUser
from app.seed import seed
from app.staff.links import issue_password_token, use_password_token
from app.staff.sessions import create_session, find_session_user
from app.staff.throttle import EMAIL_LIMIT

BASE_URL = "http://localhost:8080"
EMAIL = "sam.staff@example.com"
NEW_PASSWORD = "a new password"  # noqa: S105 - a test password
TOKEN = re.compile(r"/staff/set-password#t=([A-Za-z0-9_-]+)")


@pytest.fixture
def seeded(db_session: Session) -> Session:
    seed(db_session)
    return db_session


def send_all(session: Session, sender: FakeSender) -> None:
    """Make every queued email due now, then let the worker's outbox send them."""
    for email in session.scalars(select(EmailLog).where(EmailLog.status == "queued")):
        email.next_attempt_at = utc_now()
    session.commit()
    send_due_emails(session, sender, utc_now(), BASE_URL)


def token_in(sender: FakeSender) -> str:
    found = TOKEN.search(sender.sent[-1].text)
    assert found, sender.sent[-1].text
    return found.group(1)


def set_password(client: TestClient, token: str, password: str = NEW_PASSWORD) -> int:
    response = client.post(
        "/api/staff/set-password",
        json={"token": token, "password": password},
        headers={"Origin": ORIGIN},
    )
    return response.status_code


def forgot(client: TestClient, email: str = EMAIL) -> int:
    response = client.post(
        "/api/staff/forgot-password", json={"email": email}, headers={"Origin": ORIGIN}
    )
    assert response.json() == {"detail": "If that address has an account, we've emailed a link"}
    return response.status_code


def queue_invite(session: Session, user: StaffUser) -> None:
    session.add(EmailLog(template="staff_invite", staff_user_id=user.id, recipient=user.email))
    session.flush()


def test_invite_email_link_sets_password_and_logs_in(
    api_client: TestClient, seeded: Session
) -> None:
    user = make_staff(seeded, password=None)
    queue_invite(seeded, user)
    sender = FakeSender()
    send_all(seeded, sender)
    assert sender.sent[0].to == EMAIL
    assert "72 hours" in sender.sent[0].text
    assert set_password(api_client, token_in(sender)) == 200
    assert api_client.get("/api/staff/me").status_code == 200


def test_set_password_link_works_once(api_client: TestClient, seeded: Session) -> None:
    token = issue_password_token(seeded, make_staff(seeded, password=None), "invite", utc_now())
    assert set_password(api_client, token) == 200
    assert set_password(api_client, token) == 400


def test_bad_link_gets_one_message(api_client: TestClient, seeded: Session) -> None:
    for token in ["nope", "x" * 5000, ""]:
        response = api_client.post(
            "/api/staff/set-password",
            json={"token": token, "password": NEW_PASSWORD},
            headers={"Origin": ORIGIN},
        )
        assert response.status_code == 400
        assert response.json() == {"detail": "This link isn't valid any more"}


def test_short_password_is_422_and_keeps_the_link(api_client: TestClient, seeded: Session) -> None:
    token = issue_password_token(seeded, make_staff(seeded, password=None), "invite", utc_now())
    assert set_password(api_client, token, "short") == 422
    assert set_password(api_client, token) == 200


def test_reset_link_expires_after_one_hour(seeded: Session) -> None:
    user = make_staff(seeded)
    now = utc_now()
    token = issue_password_token(seeded, user, "reset", now)
    assert use_password_token(seeded, token, now + timedelta(hours=1)) is None
    other = issue_password_token(seeded, user, "reset", now)
    assert use_password_token(seeded, other, now + timedelta(minutes=59)) == user


def test_invite_link_lasts_72_hours(seeded: Session) -> None:
    user = make_staff(seeded, password=None)
    now = utc_now()
    token = issue_password_token(seeded, user, "invite", now)
    assert use_password_token(seeded, token, now + timedelta(hours=72)) is None
    other = issue_password_token(seeded, user, "invite", now)
    assert use_password_token(seeded, other, now + timedelta(hours=71)) == user


def test_new_link_cancels_the_old_one(seeded: Session) -> None:
    user = make_staff(seeded)
    now = utc_now()
    old = issue_password_token(seeded, user, "reset", now)
    new = issue_password_token(seeded, user, "reset", now)
    assert use_password_token(seeded, old, now) is None
    assert use_password_token(seeded, new, now) == user


def test_link_for_removed_user_doesnt_work(seeded: Session) -> None:
    user = make_staff(seeded)
    token = issue_password_token(seeded, user, "reset", utc_now())
    user.active = False
    seeded.flush()
    assert use_password_token(seeded, token, utc_now()) is None


def test_set_password_ends_other_sessions(api_client: TestClient, seeded: Session) -> None:
    user = make_staff(seeded)
    old_session = create_session(seeded, user, utc_now())
    token = issue_password_token(seeded, user, "reset", utc_now())
    assert set_password(api_client, token) == 200
    assert find_session_user(seeded, old_session, utc_now()) is None


def test_forgot_password_is_202_for_unknown_and_known_emails(
    api_client: TestClient, seeded: Session
) -> None:
    make_staff(seeded)
    assert forgot(api_client, "nobody@example.com") == 202
    assert seeded.scalar(select(func.count()).select_from(EmailLog)) == 0
    assert forgot(api_client, " Sam.Staff@Example.com ") == 202
    assert seeded.scalars(select(EmailLog.template)).all() == ["password_reset"]


def test_forgot_password_keeps_the_old_password_working(
    api_client: TestClient, seeded: Session
) -> None:
    make_staff(seeded)
    forgot(api_client)
    response = api_client.post(
        "/api/staff/login",
        json={"email": EMAIL, "password": STAFF_PASSWORD},
        headers={"Origin": ORIGIN},
    )
    assert response.status_code == 200


def test_forgot_password_for_removed_user_sends_nothing(
    api_client: TestClient, seeded: Session
) -> None:
    make_staff(seeded, active=False)
    assert forgot(api_client) == 202
    assert seeded.scalar(select(func.count()).select_from(EmailLog)) == 0


def test_forgot_password_counts_towards_the_lock(api_client: TestClient, seeded: Session) -> None:
    make_staff(seeded)
    for _ in range(EMAIL_LIMIT):
        forgot(api_client)
    sent = seeded.scalar(select(func.count()).select_from(EmailLog))
    assert sent == EMAIL_LIMIT
    forgot(api_client)  # locked now: still 202, but nothing more is sent
    assert seeded.scalar(select(func.count()).select_from(EmailLog)) == sent


def test_staff_email_for_removed_user_is_skipped(seeded: Session) -> None:
    user = make_staff(seeded)
    queue_invite(seeded, user)
    user.active = False
    sender = FakeSender()
    send_all(seeded, sender)
    assert sender.sent == []
    assert seeded.scalars(select(EmailLog.status)).one() == "skipped"


def test_failed_send_keeps_no_token(seeded: Session) -> None:
    queue_invite(seeded, make_staff(seeded, password=None))
    send_all(seeded, FakeSender(fail=True))
    assert seeded.scalar(select(func.count()).select_from(PasswordToken)) == 0


def test_no_plain_token_in_email_log_or_password_tokens(seeded: Session) -> None:
    queue_invite(seeded, make_staff(seeded, password=None))
    sender = FakeSender()
    send_all(seeded, sender)
    token = token_in(sender)
    stored = [str(row.context) for row in seeded.scalars(select(EmailLog))]
    stored += list(seeded.scalars(select(PasswordToken.token_hash)))
    assert all(token not in value for value in stored)


# --- the first admin -----------------------------------------------------------


@pytest.fixture
def fresh_app_url(fresh_database_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """A migrated, seeded database of its own, which get_config() points at."""
    command.upgrade(alembic_config(fresh_database_url), "head")
    engine = make_engine(fresh_database_url)
    with Session(engine) as session:
        seed(session)
        session.commit()
    engine.dispose()
    monkeypatch.setenv("DATABASE_URL", fresh_database_url)
    get_config.cache_clear()
    yield fresh_database_url
    get_config.cache_clear()


def test_create_admin_prints_a_working_link(
    fresh_app_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert create_admin.main(["--name", "Alex Admin", "--email", "Alex@Example.com"]) == 0
    printed = capsys.readouterr().out
    assert "Set the password within 72 hours" in printed
    found = TOKEN.search(printed)
    assert found
    with TestClient(create_app(AppConfig(database_url=fresh_app_url))) as client:
        assert set_password(client, found.group(1)) == 200
        assert client.get("/api/staff/me").json()["role"] == "admin"
    engine = make_engine(fresh_app_url)
    with Session(engine) as session:
        entry = session.scalars(select(AuditEntry)).one()
        assert (entry.action, entry.staff_user_id) == ("staff.invite", None)
        assert session.scalar(select(func.count()).select_from(EmailLog)) == 0
    engine.dispose()


def test_create_admin_twice_is_refused(
    fresh_app_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert create_admin.main(["--name", "A", "--email", "a@example.com"]) == 0
    assert create_admin.main(["--name", "A", "--email", "A@example.com"]) == 1
    assert "already exists" in capsys.readouterr().err
