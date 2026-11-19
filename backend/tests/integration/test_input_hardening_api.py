"""Inputs that used to reach the database and fail there now get a 422."""

from datetime import UTC, datetime
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.clock import utc_now
from app.seed import seed

NOW = datetime(2026, 11, 9, 9, tzinfo=UTC)
MOT_0800 = "2026-11-10T08:00:00+00:00"
NUL = "Please remove unusual characters"
DETAILS: dict[str, Any] = {
    "name": "Sam Driver",
    "phone": "07700 900123",
    "email": "sam@example.com",
    "registration": "AB12CDE",
    "make": "Ford",
    "model": "Focus",
}


@pytest.fixture
def public(api_client: TestClient, db_session: Session) -> TestClient:
    seed(db_session)
    cast(FastAPI, api_client.app).dependency_overrides[utc_now] = lambda: NOW
    return api_client


def test_nul_in_public_forms_is_422(public: TestClient) -> None:
    enquiry = DETAILS | {"description": "Rattle from the\x00 front left"}
    response = public.post("/api/enquiries", json=enquiry)
    assert (response.status_code, response.json()) == (422, {"detail": f"description: {NUL}"})
    created = public.post("/api/holds", json={"services": ["mot-test"], "start": MOT_0800}).json()
    body = {"hold_token": created["hold_token"]} | DETAILS | {"name": "Sam\x00"}
    response = public.post(f"/api/holds/{created['reference']}/checkout", json=body)
    assert (response.status_code, response.json()) == (422, {"detail": f"name: {NUL}"})


@pytest.mark.parametrize("bad", ["99999999999", "0", "-1"])
def test_out_of_range_ids_are_422(admin_client: TestClient, bad: str) -> None:
    for method, path in [
        ("GET", f"/api/staff/enquiries/{bad}"),
        ("DELETE", f"/api/staff/blocks/{bad}"),
        ("DELETE", f"/api/staff/settings/hours/{bad}"),
        ("PATCH", f"/api/staff/team/{bad}"),
    ]:
        response = admin_client.request(method, path, json={})
        assert response.status_code == 422, (method, path, response.status_code)


def week(open_time: str) -> list[dict[str, Any]]:
    return [{"weekday": d, "open": open_time, "close": "17:30", "breaks": []} for d in range(7)]


@pytest.mark.parametrize("open_time", ["08:00+01:00", "08:00:30"])
def test_hours_refuse_zone_and_seconds(
    admin_client: TestClient, db_session: Session, open_time: str
) -> None:
    seed(db_session)
    admin_client.app.dependency_overrides[utc_now] = lambda: NOW  # type: ignore[attr-defined]
    body = {"starts_on": "2026-12-01", "days": week(open_time)}
    response = admin_client.post("/api/staff/settings/hours", json=body)
    assert response.status_code == 422, response.text


def test_hours_refuse_zone_in_breaks(admin_client: TestClient, db_session: Session) -> None:
    seed(db_session)
    admin_client.app.dependency_overrides[utc_now] = lambda: NOW  # type: ignore[attr-defined]
    days = week("08:00")
    days[0]["breaks"] = [{"start": "12:30+01:00", "end": "13:00"}]
    response = admin_client.post(
        "/api/staff/settings/hours", json={"starts_on": "2026-12-01", "days": days}
    )
    assert response.status_code == 422, response.text


def test_api_sends_nosniff(public: TestClient) -> None:
    assert public.get("/api/health").headers["X-Content-Type-Options"] == "nosniff"
    assert public.get("/api/services").headers["X-Content-Type-Options"] == "nosniff"


@pytest.mark.parametrize("path", ["/api/staff/login", "/api/staff/forgot-password"])
def test_nul_in_staff_login_email_is_422(public: TestClient, path: str) -> None:
    body = {"email": "a\x00@example.com", "password": "whatever"}
    response = public.post(path, json=body, headers={"Origin": "http://localhost:8080"})
    assert response.status_code == 422, response.text
