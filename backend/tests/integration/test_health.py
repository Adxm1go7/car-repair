from fastapi.testclient import TestClient

from app.config import AppConfig
from app.main import create_app


def test_health_reports_ok_when_database_reachable(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_health_reports_503_when_database_unreachable() -> None:
    app = create_app(AppConfig(database_url="postgresql+psycopg://u:p@127.0.0.1:1/none"))
    response = TestClient(app).get("/api/health")
    assert response.status_code == 503
    assert response.json() == {"status": "error", "database": "unavailable"}
