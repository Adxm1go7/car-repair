"""One `app.request` line per request: no query string, and a request id the client sees."""

import logging
import re

import pytest
from fastapi.testclient import TestClient

from app.config import AppConfig
from app.main import create_app


def request_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == "app.request"]


def test_request_is_logged_without_query(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="app.request"):
        response = client.get("/api/no-such-route?services=mot&email=sam@example.com")
    [rec] = request_records(caplog)
    assert rec.__dict__["method"] == "GET"
    assert rec.__dict__["path"] == "/api/no-such-route"
    assert rec.__dict__["status"] == response.status_code
    assert isinstance(rec.__dict__["duration_ms"], int)
    assert re.fullmatch(r"[0-9a-f]{32}", rec.__dict__["request_id"])
    assert response.headers["X-Request-ID"] == rec.__dict__["request_id"]
    assert "services=" not in rec.getMessage()
    assert all("services=" not in str(value) for value in rec.__dict__.values())


def test_failed_request_is_logged_once(postgres_url: str, caplog: pytest.LogCaptureFixture) -> None:
    app = create_app(AppConfig(database_url=postgres_url, environment="test"))

    @app.get("/api/boom")
    def boom() -> None:
        raise RuntimeError("boom")

    with (
        TestClient(app, raise_server_exceptions=False) as client,
        caplog.at_level(logging.INFO, logger="app.request"),
    ):
        response = client.get("/api/boom")
    assert response.status_code == 500
    [rec] = request_records(caplog)
    assert rec.__dict__["status"] == 500
