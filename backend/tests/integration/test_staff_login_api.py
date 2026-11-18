"""Logging in and out as staff."""

import pytest
from conftest import ORIGIN, STAFF_PASSWORD, ClientFor
from factories import make_staff
from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api import staff_auth
from app.config import AppConfig
from app.models import LoginAttempt
from app.staff.sessions import SESSION_CAP
from app.staff.throttle import EMAIL_LIMIT, IP_LIMIT

EMAIL = "sam.staff@example.com"
BAD_PASSWORD = "wrong password"  # noqa: S105 - a test password
WRONG = {"detail": "Email or password is wrong"}


def login(client: TestClient, email: str = EMAIL, password: str = STAFF_PASSWORD) -> Response:
    return client.post(
        "/api/staff/login", json={"email": email, "password": password}, headers={"Origin": ORIGIN}
    )


def test_login_sets_an_httponly_strict_cookie(api_client: TestClient, db_session: Session) -> None:
    make_staff(db_session)
    response = login(api_client)
    assert response.status_code == 200
    assert response.json() == {
        "id": response.json()["id"],
        "name": "Sam Staff",
        "email": EMAIL,
        "role": "staff",
    }
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("staff_session=")
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie
    assert "Path=/api/staff" in cookie
    assert "Secure" not in cookie


def test_login_email_ignores_case_and_spaces(api_client: TestClient, db_session: Session) -> None:
    make_staff(db_session)
    assert login(api_client, email="  Sam.Staff@Example.com ").status_code == 200


def test_wrong_password_unknown_email_and_inactive_all_give_the_same_401(
    api_client: TestClient, db_session: Session
) -> None:
    make_staff(db_session)
    make_staff(db_session, email="gone@example.com", active=False)
    make_staff(db_session, email="invited@example.com", password=None)
    for email, password in [
        (EMAIL, BAD_PASSWORD),
        ("nobody@example.com", STAFF_PASSWORD),
        ("gone@example.com", STAFF_PASSWORD),
        ("invited@example.com", STAFF_PASSWORD),
    ]:
        response = login(api_client, email, password)
        assert response.status_code == 401
        assert response.json() == WRONG
        assert "set-cookie" not in response.headers


def test_locked_email_gets_401_even_with_the_right_password(
    api_client: TestClient, db_session: Session
) -> None:
    make_staff(db_session)
    for _ in range(EMAIL_LIMIT):
        login(api_client, password=BAD_PASSWORD)
    response = login(api_client)
    assert response.status_code == 401
    assert response.json() == WRONG


def test_me_returns_the_user(staff_client: TestClient) -> None:
    response = staff_client.get("/api/staff/me")
    assert response.status_code == 200
    assert response.json()["email"] == EMAIL


def test_logout_ends_the_session(staff_client: TestClient) -> None:
    cookie = staff_client.cookies.get("staff_session")
    response = staff_client.post("/api/staff/logout")
    assert response.status_code == 204
    assert (
        'staff_session=""' in response.headers["set-cookie"]
        or "Max-Age=0" in (response.headers["set-cookie"])
    )
    # The old cookie no longer works, even if the browser kept it.
    staff_client.cookies.set("staff_session", cookie or "", path="/api/staff")
    assert staff_client.get("/api/staff/me").status_code == 401


def test_cookie_lasts_the_30_day_cap(api_client: TestClient, db_session: Session) -> None:
    # The server ends a session after 7 idle days; the cookie mustn't end it sooner for
    # someone who uses the app every day.
    make_staff(db_session)
    cookie = login(api_client).headers["set-cookie"]
    assert f"Max-Age={int(SESSION_CAP.total_seconds())}" in cookie


def test_an_account_without_a_password_still_checks_a_hash(
    api_client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Otherwise an invited email answers faster than an unknown one, which gives it away.
    checked: list[str | None] = []

    def spy(password: str, stored: str | None) -> bool:
        checked.append(stored)
        return False

    monkeypatch.setattr(staff_auth, "password_matches", spy)
    make_staff(db_session, email="invited@example.com", password=None)
    assert login(api_client, "invited@example.com").status_code == 401
    assert checked and checked[0] is not None


def _bad_logins_from(client: TestClient, forwarded_for: str) -> None:
    """IP_LIMIT failures, each for a different email so no email locks."""
    for i in range(IP_LIMIT):
        client.post(
            "/api/staff/login",
            json={"email": f"nobody{i}@example.com", "password": BAD_PASSWORD},
            headers={"Origin": ORIGIN, "X-Forwarded-For": forwarded_for},
        )


def _login_from(client: TestClient, forwarded_for: str) -> Response:
    return client.post(
        "/api/staff/login",
        json={"email": EMAIL, "password": STAFF_PASSWORD},
        headers={"Origin": ORIGIN, "X-Forwarded-For": forwarded_for},
    )


def test_forwarded_ip_is_counted_when_it_comes_from_a_trusted_proxy(
    client_for: ClientFor, db_session: Session, migrated_url: str
) -> None:
    make_staff(db_session)
    config = AppConfig(database_url=migrated_url, trusted_proxies="testclient")
    with client_for(config) as client:
        _bad_logins_from(client, "203.0.113.9")
        # Someone else, behind the same proxy, isn't locked out by that address.
        assert _login_from(client, "198.51.100.7").status_code == 200
    ips = set(db_session.scalars(select(LoginAttempt.ip)))
    assert ips == {"203.0.113.9", "198.51.100.7"}


def test_forwarded_ip_is_ignored_from_anyone_else(
    api_client: TestClient, db_session: Session
) -> None:
    # The default trusts only 127.0.0.1, so a made-up header can't dodge the IP limit.
    make_staff(db_session)
    _bad_logins_from(api_client, "203.0.113.9")
    assert _login_from(api_client, "198.51.100.7").status_code == 401


def test_secure_cookie_when_base_url_is_https(
    client_for: ClientFor, db_session: Session, migrated_url: str
) -> None:
    make_staff(db_session)
    config = AppConfig(database_url=migrated_url, public_base_url="https://garage.example")
    with client_for(config) as client:
        response = client.post(
            "/api/staff/login",
            json={"email": EMAIL, "password": STAFF_PASSWORD},
            headers={"Origin": "https://garage.example"},
        )
    assert response.status_code == 200
    assert "Secure" in response.headers["set-cookie"]
