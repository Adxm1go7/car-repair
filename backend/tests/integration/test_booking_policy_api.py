"""GET /api/booking-policy: what the booking page needs to know before it asks for times."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Setting
from app.seed import seed


@pytest.fixture
def client(api_client: TestClient, db_session: Session) -> TestClient:
    seed(db_session)
    return api_client


def test_policy_shape(client: TestClient) -> None:
    response = client.get("/api/booking-policy")
    assert response.status_code == 200
    assert response.json() == {"booking_window_days": 60, "slot_hold_minutes": 5}


@pytest.mark.parametrize("key", ["booking_window_days", "slot_hold_minutes"])
def test_policy_503_when_setting_broken(client: TestClient, db_session: Session, key: str) -> None:
    setting = db_session.get(Setting, key)
    assert setting is not None
    setting.value = "soon"
    db_session.flush()
    assert client.get("/api/booking-policy").status_code == 503
