"""Every 422 has the same shape: {"detail": "<string>"}, so the frontend reads one thing."""

from datetime import UTC, datetime
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.clock import utc_now
from app.seed import seed

NOW = datetime(2026, 11, 9, 9, tzinfo=UTC)


@pytest.fixture
def client(api_client: TestClient, db_session: Session) -> TestClient:
    seed(db_session)
    cast(FastAPI, api_client.app).dependency_overrides[utc_now] = lambda: NOW
    return api_client


def test_schema_errors_have_a_string_detail_naming_the_field(client: TestClient) -> None:
    response = client.get("/api/availability", params={"services": "mot-test", "date": "nope"})
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert isinstance(detail, str)
    assert detail.startswith("date: ")


def test_missing_parameter_has_a_string_detail(client: TestClient) -> None:
    response = client.get("/api/availability", params={"date": "2026-11-10"})
    assert response.status_code == 422
    assert response.json()["detail"].startswith("services: ")
