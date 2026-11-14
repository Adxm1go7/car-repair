"""POST /api/demo/checkout/{demo_session}: demo payments, only when no Stripe key is set."""

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock import utc_now
from app.config import AppConfig
from app.db import get_session
from app.main import create_app
from app.models import Booking
from app.seed import seed

NOW = datetime(2026, 11, 9, 9, tzinfo=UTC)
MOT_0800 = "2026-11-10T08:00:00+00:00"
DETAILS = {
    "name": "Sam Driver",
    "phone": "07700 900123",
    "email": "sam@example.com",
    "registration": "AB12CDE",
    "make": "Ford",
    "model": "Focus",
}


def app_client(db_session: Session, config: AppConfig) -> Iterator[TestClient]:
    """The real provider choice (no fake): demo without a key, Stripe with one."""
    seed(db_session)
    app = create_app(config)

    def use_test_session() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_session] = use_test_session
    app.dependency_overrides[utc_now] = lambda: NOW
    with TestClient(app) as client:
        yield client


@pytest.fixture
def demo(db_session: Session, migrated_url: str) -> Iterator[TestClient]:
    yield from app_client(db_session, AppConfig(database_url=migrated_url))


def paying(client: TestClient) -> dict[str, Any]:
    created = cast(
        dict[str, Any],
        client.post("/api/holds", json={"services": ["mot-test"], "start": MOT_0800}).json(),
    )
    body = {"hold_token": created["hold_token"]} | DETAILS
    started = client.post(f"/api/holds/{created['reference']}/checkout", json=body).json()
    assert started["client_secret"] is None
    assert started["demo_session"].startswith("demo_")
    return created | {"demo_session": started["demo_session"]}


def pay(client: TestClient, demo_session: str, outcome: str = "pay") -> Any:
    return client.post(f"/api/demo/checkout/{demo_session}", json={"outcome": outcome})


def stored(session: Session, reference: str) -> Booking:
    session.expire_all()
    return session.scalars(select(Booking).where(Booking.reference == reference)).one()


def test_demo_pay_confirms_the_booking(demo: TestClient, db_session: Session) -> None:
    created = paying(demo)
    response = pay(demo, created["demo_session"])
    assert response.status_code == 200
    assert response.json() == {"status": "confirmed"}
    booking = stored(db_session, created["reference"])
    assert (booking.status, booking.deposit_status) == ("confirmed", "paid")


def test_demo_decline_changes_nothing(demo: TestClient, db_session: Session) -> None:
    created = paying(demo)
    response = pay(demo, created["demo_session"], "decline")
    assert response.status_code == 402
    assert response.json() == {"detail": "Your card was declined (demo)"}
    booking = stored(db_session, created["reference"])
    assert (booking.status, booking.deposit_status) == ("held", "unpaid")


def test_demo_pay_twice_is_harmless(demo: TestClient, db_session: Session) -> None:
    created = paying(demo)
    pay(demo, created["demo_session"])
    again = pay(demo, created["demo_session"])
    assert again.status_code == 200
    assert again.json() == {"status": "confirmed"}


def test_demo_pay_after_release_is_404(demo: TestClient) -> None:
    created = paying(demo)
    release = {"hold_token": created["hold_token"]}
    demo.request("DELETE", f"/api/holds/{created['reference']}", json=release)
    assert pay(demo, created["demo_session"]).status_code == 404


def test_demo_unknown_session_is_404(demo: TestClient) -> None:
    assert pay(demo, "demo_nobody").status_code == 404


def test_demo_bad_outcome_is_422(demo: TestClient) -> None:
    created = paying(demo)
    assert pay(demo, created["demo_session"], "maybe").status_code == 422


def test_demo_endpoint_absent_with_stripe(db_session: Session, migrated_url: str) -> None:
    config = AppConfig(
        database_url=migrated_url,
        stripe_secret_key="sk_test_x",  # noqa: S106 - not a real key
        stripe_publishable_key="pk_test_x",
    )
    for client in app_client(db_session, config):
        assert pay(client, "demo_anything").status_code == 404
