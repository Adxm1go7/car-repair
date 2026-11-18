"""Login lockout: 10 failures for one email, or 20 from one IP, within 15 minutes."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import LoginAttempt
from app.staff.throttle import delete_old_attempts, is_locked, record_attempt

NOW = datetime(2026, 11, 16, 9, tzinfo=UTC)
EMAIL = "sam@example.com"


def fail(session: Session, times: int, *, email: str = EMAIL, ip: str = "10.0.0.1") -> None:
    for _ in range(times):
        record_attempt(session, email, ip, False, NOW)


def test_tenth_failure_locks_the_email(db_session: Session) -> None:
    fail(db_session, 9)
    assert not is_locked(db_session, EMAIL, "10.0.0.2", NOW)
    fail(db_session, 1)
    assert is_locked(db_session, EMAIL, "10.0.0.2", NOW)


def test_lock_ends_after_15_minutes(db_session: Session) -> None:
    fail(db_session, 10)
    assert is_locked(
        db_session, EMAIL, "10.0.0.2", NOW + timedelta(minutes=15) - timedelta(seconds=1)
    )
    assert not is_locked(db_session, EMAIL, "10.0.0.2", NOW + timedelta(minutes=15))


def test_twenty_failures_from_one_ip_lock_it(db_session: Session) -> None:
    for n in range(19):
        record_attempt(db_session, f"user{n}@example.com", "10.0.0.9", False, NOW)
    assert not is_locked(db_session, "new@example.com", "10.0.0.9", NOW)
    record_attempt(db_session, "user19@example.com", "10.0.0.9", False, NOW)
    assert is_locked(db_session, "new@example.com", "10.0.0.9", NOW)


def test_email_case_doesnt_dodge_the_lock(db_session: Session) -> None:
    fail(db_session, 5, email="Sam@Example.com")
    fail(db_session, 5, email=" sam@example.com ")
    assert is_locked(db_session, "SAM@example.COM", "10.0.0.2", NOW)


def test_successes_dont_count(db_session: Session) -> None:
    for _ in range(12):
        record_attempt(db_session, EMAIL, "10.0.0.1", True, NOW)
    assert not is_locked(db_session, EMAIL, "10.0.0.1", NOW)


def test_old_attempts_are_deleted_after_a_day(db_session: Session) -> None:
    record_attempt(db_session, EMAIL, "10.0.0.1", False, NOW - timedelta(days=1, seconds=1))
    record_attempt(db_session, EMAIL, "10.0.0.1", False, NOW)
    assert delete_old_attempts(db_session, NOW) == 1
    assert db_session.scalar(select(func.count()).select_from(LoginAttempt)) == 1
