"""The rate-limit counter: attempts are counted per action and IP, and kept apart from the
route's own transaction. Off in development."""

from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from conftest import ClientFor
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.clock import utc_now
from app.config import AppConfig
from app.limits import TooManyAttempts, check_and_record, delete_old_counts
from app.models import RequestCount
from app.seed import seed

NOW = datetime(2026, 11, 20, 9, tzinfo=UTC)
IP = "203.0.113.7"
ENQUIRY: dict[str, Any] = {
    "name": "Sam Driver",
    "phone": "07700 900123",
    "email": "sam@example.com",
    "registration": "AB12CDE",
    "make": "Ford",
    "model": "Focus",
    "description": "Rattle from the front left when braking",
}


def counts(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(RequestCount)) or 0


def test_under_limit_records_and_commits(db_session: Session) -> None:
    for _ in range(5):
        check_and_record(db_session, "enquiry", IP, NOW)
    db_session.rollback()  # a route that fails afterwards can't undo the count
    assert counts(db_session) == 5


def test_at_limit_raises_and_records_nothing(db_session: Session) -> None:
    for _ in range(5):
        check_and_record(db_session, "enquiry", IP, NOW)
    with pytest.raises(TooManyAttempts) as refused:
        check_and_record(db_session, "enquiry", IP, NOW)
    assert refused.value.retry_after == 3600
    assert counts(db_session) == 5


def test_retry_after_comes_from_the_oldest_attempt(db_session: Session) -> None:
    for minutes in (50, 30, 10, 5, 1):
        check_and_record(db_session, "enquiry", IP, NOW - timedelta(minutes=minutes))
    with pytest.raises(TooManyAttempts) as refused:
        check_and_record(db_session, "enquiry", IP, NOW)
    assert refused.value.retry_after == 600  # the 50-minute-old one leaves in 10 minutes


def test_window_passes(db_session: Session) -> None:
    for _ in range(5):
        check_and_record(db_session, "enquiry", IP, NOW - timedelta(minutes=61))
    check_and_record(db_session, "enquiry", IP, NOW)  # the old ones no longer count
    assert counts(db_session) == 6


def test_actions_and_ips_count_apart(db_session: Session) -> None:
    for _ in range(5):
        check_and_record(db_session, "enquiry", IP, NOW)
    check_and_record(db_session, "hold", IP, NOW)
    check_and_record(db_session, "enquiry", "198.51.100.1", NOW)
    assert counts(db_session) == 7


def test_worker_deletes_old_counts(db_session: Session) -> None:
    check_and_record(db_session, "hold", IP, NOW - timedelta(days=2))
    check_and_record(db_session, "hold", IP, NOW - timedelta(hours=1))
    assert delete_old_counts(db_session, NOW) == 1
    assert counts(db_session) == 1


def test_development_records_nothing(
    client_for: ClientFor, db_session: Session, migrated_url: str
) -> None:
    seed(db_session)
    config = AppConfig(database_url=migrated_url, environment="development")
    with client_for(config) as client:
        cast(FastAPI, client.app).dependency_overrides[utc_now] = lambda: NOW
        for _ in range(7):
            assert client.post("/api/enquiries", json=ENQUIRY).status_code == 201
    assert counts(db_session) == 0
