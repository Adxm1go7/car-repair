"""Every staff route checks the session, every admin route the role, and every write the Origin.

The walks below go through the app's real routes, so a route added later without its
guard fails here.
"""

import re
from collections.abc import Iterator
from datetime import timedelta

import pytest
from conftest import ORIGIN, ClientFor
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock import utc_now
from app.config import AppConfig
from app.models import StaffUser
from app.staff.deps import ADMIN_STAFF_PREFIXES, PUBLIC_STAFF_PATHS

PATH_VALUES = {
    "reference": "ABCD-EFGH",
    "user_id": "1",
    "block_id": "1",
    "service_id": "1",
    "bay_id": "1",
    "timetable_id": "1",
    "enquiry_id": "1",
}
WRITES = {"POST", "PATCH", "PUT", "DELETE"}


def fill(path: str) -> str:
    return re.sub(r"\{(\w+)\}", lambda match: PATH_VALUES[match.group(1)], path)


def staff_routes(client: TestClient) -> Iterator[tuple[str, str]]:
    """(method, filled path) for every guarded staff route, from the app's OpenAPI paths."""
    app = client.app
    assert isinstance(app, FastAPI)
    for path, operations in app.openapi()["paths"].items():
        if not path.startswith("/api/staff") or path in PUBLIC_STAFF_PATHS:
            continue
        for method in operations:
            yield method.upper(), path


def call(client: TestClient, method: str, path: str) -> int:
    body: dict[str, object] | None = {} if method in WRITES else None
    return client.request(method, fill(path), json=body, headers={"Origin": ORIGIN}).status_code


def test_every_staff_route_needs_a_session(api_client: TestClient) -> None:
    routes = list(staff_routes(api_client))
    assert len(routes) >= 2  # me and logout at least: the walk can't pass by finding nothing
    for method, path in routes:
        assert call(api_client, method, path) == 401, (method, path)


def test_staff_get_403_on_every_admin_route(staff_client: TestClient) -> None:
    admin = [(m, p) for m, p in staff_routes(staff_client) if p.startswith(ADMIN_STAFF_PREFIXES)]
    assert admin  # the team routes at least: the walk can't pass by finding nothing
    for method, path in admin:
        assert call(staff_client, method, path) == 403, (method, path)


def test_settings_routes_are_admin_only(staff_client: TestClient) -> None:
    admin = {p for _, p in staff_routes(staff_client) if p.startswith(ADMIN_STAFF_PREFIXES)}
    assert {"/api/staff/settings/services", "/api/staff/settings/bays"} <= admin
    assert {"/api/staff/settings/bay-types", "/api/staff/settings/hours"} <= admin


def test_expired_session_cookie_is_401(staff_client: TestClient) -> None:
    later = utc_now() + timedelta(days=8)
    staff_client.app.dependency_overrides[utc_now] = lambda: later  # type: ignore[attr-defined]
    assert staff_client.get("/api/staff/me").status_code == 401


def test_removed_user_cookie_is_401(staff_client: TestClient, db_session: Session) -> None:
    user = db_session.scalars(select(StaffUser)).one()
    user.active = False
    db_session.flush()
    assert staff_client.get("/api/staff/me").status_code == 401


def test_write_without_origin_is_403(staff_client: TestClient) -> None:
    del staff_client.headers["Origin"]
    assert staff_client.post("/api/staff/logout").status_code == 403


def test_write_with_foreign_origin_is_403(staff_client: TestClient) -> None:
    response = staff_client.post("/api/staff/logout", headers={"Origin": "https://evil.example"})
    assert response.status_code == 403


def test_login_needs_the_origin_too(api_client: TestClient) -> None:
    response = api_client.post("/api/staff/login", json={"email": "a@b.com", "password": "x"})
    assert response.status_code == 403


def test_reads_need_no_origin(staff_client: TestClient) -> None:
    del staff_client.headers["Origin"]
    assert staff_client.get("/api/staff/me").status_code == 200


@pytest.mark.parametrize(
    ("environment", "allowed"), [("development", True), ("test", False), ("production", False)]
)
def test_dev_origin_allowed_only_in_development(
    client_for: ClientFor, migrated_url: str, environment: str, allowed: bool
) -> None:
    keys = {"stripe_secret_key": "sk_test_x", "stripe_publishable_key": "pk_test_x"}
    config = AppConfig(
        database_url=migrated_url,
        environment=environment,
        **(keys if environment == "production" else {}),  # type: ignore[arg-type]
    )
    with client_for(config) as client:
        response = client.post(
            "/api/staff/login",
            json={"email": "nobody@example.com", "password": "whatever"},
            headers={"Origin": "http://localhost:5173"},
        )
    assert response.status_code == (401 if allowed else 403)
