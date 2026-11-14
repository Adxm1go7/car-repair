"""GET /api/booking-policy: what the booking page needs to know before it asks for times."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import AppConfig
from app.db import get_session
from app.main import create_app
from app.models import Setting
from app.seed import seed

POLICY = {
    "booking_window_days": 60,
    "slot_hold_minutes": 5,
    "payment_hold_minutes": 10,
    "deposit_amount_pence": 2000,
}


@pytest.fixture
def client(api_client: TestClient, db_session: Session) -> TestClient:
    seed(db_session)
    return api_client


def test_policy_shape_in_demo_mode(client: TestClient) -> None:
    response = client.get("/api/booking-policy")
    assert response.status_code == 200
    assert response.json() == POLICY | {"payment": {"provider": "demo"}}


def test_policy_gives_the_publishable_key_only(db_session: Session, migrated_url: str) -> None:
    seed(db_session)
    config = AppConfig(
        database_url=migrated_url,
        stripe_secret_key="sk_test_secret",  # noqa: S106 - not a real key
        stripe_publishable_key="pk_test_public",
    )
    app = create_app(config)

    def use_test_session() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_session] = use_test_session
    with TestClient(app) as stripe_client:
        response = stripe_client.get("/api/booking-policy")
    assert response.json()["payment"] == {"provider": "stripe", "publishable_key": "pk_test_public"}
    assert "sk_test_secret" not in response.text


@pytest.mark.parametrize(
    "key",
    ["booking_window_days", "slot_hold_minutes", "payment_hold_minutes", "deposit_amount_pence"],
)
def test_policy_503_when_setting_broken(client: TestClient, db_session: Session, key: str) -> None:
    setting = db_session.get(Setting, key)
    assert setting is not None
    setting.value = "soon"
    db_session.flush()
    assert client.get("/api/booking-policy").status_code == 503
