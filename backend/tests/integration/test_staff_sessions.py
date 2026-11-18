"""Staff login sessions: stored as hashes, ended when idle, capped, and gone with the user."""

from datetime import UTC, datetime, timedelta

from factories import make_staff
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import StaffSession
from app.staff.sessions import (
    create_session,
    delete_expired_sessions,
    end_all_sessions,
    end_session,
    find_session_user,
)

NOW = datetime(2026, 11, 16, 9, tzinfo=UTC)


def test_new_session_finds_its_user(db_session: Session) -> None:
    user = make_staff(db_session)
    token = create_session(db_session, user, NOW)
    assert find_session_user(db_session, token, NOW) == user
    assert user.last_login_at == NOW


def test_token_is_stored_hashed(db_session: Session) -> None:
    token = create_session(db_session, make_staff(db_session), NOW)
    hashes = db_session.scalars(select(StaffSession.token_hash)).all()
    assert token not in hashes
    assert len(hashes) == 1


def test_unknown_token_finds_nobody(db_session: Session) -> None:
    create_session(db_session, make_staff(db_session), NOW)
    assert find_session_user(db_session, "nope", NOW) is None
    assert find_session_user(db_session, "x" * 5000, NOW) is None


def test_session_idle_7_days_is_gone(db_session: Session) -> None:
    user = make_staff(db_session)
    token = create_session(db_session, user, NOW)
    week = timedelta(days=7)
    assert find_session_user(db_session, token, NOW + week - timedelta(seconds=1)) == user
    # That use moved last_used_at on, so start again from a fresh session.
    other = create_session(db_session, user, NOW)
    assert find_session_user(db_session, other, NOW + week) is None


def test_session_past_30_days_is_gone_even_when_used(db_session: Session) -> None:
    user = make_staff(db_session)
    token = create_session(db_session, user, NOW)
    for day in range(1, 30):
        assert find_session_user(db_session, token, NOW + timedelta(days=day)) == user
    assert find_session_user(db_session, token, NOW + timedelta(days=30)) is None


def test_inactive_user_session_is_none(db_session: Session) -> None:
    user = make_staff(db_session)
    token = create_session(db_session, user, NOW)
    user.active = False
    db_session.flush()
    assert find_session_user(db_session, token, NOW) is None


def test_end_session(db_session: Session) -> None:
    user = make_staff(db_session)
    token = create_session(db_session, user, NOW)
    keep = create_session(db_session, user, NOW)
    end_session(db_session, token)
    assert find_session_user(db_session, token, NOW) is None
    assert find_session_user(db_session, keep, NOW) == user


def test_end_all_sessions(db_session: Session) -> None:
    user = make_staff(db_session)
    other = make_staff(db_session, email="other@example.com")
    tokens = [create_session(db_session, user, NOW) for _ in range(2)]
    kept = create_session(db_session, other, NOW)
    end_all_sessions(db_session, user.id)
    assert all(find_session_user(db_session, t, NOW) is None for t in tokens)
    assert find_session_user(db_session, kept, NOW) == other


def test_last_used_written_at_most_once_a_minute(db_session: Session) -> None:
    user = make_staff(db_session)
    token = create_session(db_session, user, NOW)
    row = db_session.scalars(select(StaffSession)).one()
    find_session_user(db_session, token, NOW + timedelta(seconds=59))
    assert row.last_used_at == NOW
    find_session_user(db_session, token, NOW + timedelta(seconds=60))
    assert row.last_used_at == NOW + timedelta(seconds=60)


def test_delete_expired_sessions(db_session: Session) -> None:
    user = make_staff(db_session)
    create_session(db_session, user, NOW - timedelta(days=8))
    live = create_session(db_session, user, NOW)
    assert delete_expired_sessions(db_session, NOW) == 1
    assert find_session_user(db_session, live, NOW) == user
