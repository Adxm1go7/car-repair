"""Logging in and out as staff."""

from conftest import ORIGIN, STAFF_PASSWORD, ClientFor
from factories import make_staff
from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy.orm import Session

from app.config import AppConfig
from app.staff.throttle import EMAIL_LIMIT

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
