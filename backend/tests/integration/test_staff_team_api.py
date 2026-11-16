"""Admins manage staff accounts: invite, change role, remove, restore, reset."""

import threading

from alembic import command
from conftest import ORIGIN, STAFF_PASSWORD, alembic_config
from factories import make_staff
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.clock import utc_now
from app.db import make_engine
from app.models import AuditEntry, EmailLog, StaffUser
from app.staff.accounts import LastAdmin, update_staff
from app.staff.sessions import create_session, find_session_user

STAFF_EMAIL = "sam.staff@example.com"


def user_by_email(session: Session, email: str) -> StaffUser:
    return session.scalars(select(StaffUser).where(StaffUser.email == email)).one()


def login(client: TestClient, email: str, password: str = STAFF_PASSWORD) -> int:
    response = client.post(
        "/api/staff/login",
        json={"email": email, "password": password},
        headers={"Origin": ORIGIN},
    )
    return response.status_code


def audit_actions(session: Session) -> list[str]:
    return list(session.scalars(select(AuditEntry.action).order_by(AuditEntry.id)))


def test_invite_queues_email_and_audits(admin_client: TestClient, db_session: Session) -> None:
    response = admin_client.post(
        "/api/staff/team",
        json={"name": "Jo Mechanic", "email": " Jo@Example.com ", "role": "staff"},
    )
    assert response.status_code == 201
    assert response.json()["state"] == "invited"
    user = user_by_email(db_session, "jo@example.com")
    assert user.password_hash is None
    assert db_session.scalars(select(EmailLog.template)).all() == ["staff_invite"]
    assert audit_actions(db_session) == ["staff.invite"]
    entry = db_session.scalars(select(AuditEntry)).one()
    assert entry.after == {
        "name": "Jo Mechanic",
        "email": "jo@example.com",
        "role": "staff",
        "active": True,
    }


def test_invite_duplicate_email_is_409(admin_client: TestClient, db_session: Session) -> None:
    make_staff(db_session)
    response = admin_client.post(
        "/api/staff/team", json={"name": "Sam", "email": "SAM.STAFF@example.com", "role": "staff"}
    )
    assert response.status_code == 409
    assert response.json() == {"detail": "That email already has an account"}


def test_invite_bad_role_or_email_is_422(admin_client: TestClient) -> None:
    for body in [
        {"name": "Jo", "email": "jo@example.com", "role": "owner"},
        {"name": "Jo", "email": "not an email", "role": "staff"},
        {"name": " ", "email": "jo@example.com", "role": "staff"},
    ]:
        assert admin_client.post("/api/staff/team", json=body).status_code == 422


def test_role_change_applies_on_next_request(admin_client: TestClient, db_session: Session) -> None:
    other = make_staff(db_session, role="admin", email="other.admin@example.com")
    me = user_by_email(db_session, "alex.admin@example.com")
    response = admin_client.patch(f"/api/staff/team/{me.id}", json={"role": "staff"})
    assert response.status_code == 200
    assert admin_client.get("/api/staff/team").status_code == 403
    assert other.role == "admin"
    assert audit_actions(db_session) == ["staff.role"]


def test_remove_ends_sessions_and_old_password_fails(
    admin_client: TestClient, db_session: Session
) -> None:
    user = make_staff(db_session)
    token = create_session(db_session, user, utc_now())
    response = admin_client.patch(f"/api/staff/team/{user.id}", json={"active": False})
    assert response.status_code == 200
    assert response.json()["state"] == "removed"
    assert find_session_user(db_session, token, utc_now()) is None
    assert user.password_hash is None
    assert login(admin_client, STAFF_EMAIL) == 401
    assert audit_actions(db_session) == ["staff.remove"]


def test_restore_sends_a_new_link_and_old_password_still_fails(
    admin_client: TestClient, db_session: Session
) -> None:
    user = make_staff(db_session, active=False, password=None)
    response = admin_client.patch(f"/api/staff/team/{user.id}", json={"active": True})
    assert response.status_code == 200
    assert user.active
    assert login(admin_client, STAFF_EMAIL) == 401
    assert db_session.scalars(select(EmailLog.template)).all() == ["staff_invite"]
    assert audit_actions(db_session) == ["staff.restore"]


def test_admin_reset_locks_out_until_the_link_is_used(
    admin_client: TestClient, db_session: Session
) -> None:
    user = make_staff(db_session)
    token = create_session(db_session, user, utc_now())
    response = admin_client.post(f"/api/staff/team/{user.id}/reset-password")
    assert response.status_code == 202
    assert find_session_user(db_session, token, utc_now()) is None
    assert login(admin_client, STAFF_EMAIL) == 401
    assert db_session.scalars(select(EmailLog.template)).all() == ["password_reset"]
    assert audit_actions(db_session) == ["staff.reset_password"]


def test_last_admin_cannot_be_removed_or_demoted(
    admin_client: TestClient, db_session: Session
) -> None:
    me = user_by_email(db_session, "alex.admin@example.com")
    for change in [{"active": False}, {"role": "staff"}]:
        response = admin_client.patch(f"/api/staff/team/{me.id}", json=change)
        assert response.status_code == 409
        assert response.json() == {"detail": "The garage needs at least one admin"}
    assert (me.role, me.active) == ("admin", True)
    assert audit_actions(db_session) == []


def test_unknown_user_is_404(admin_client: TestClient) -> None:
    assert admin_client.patch("/api/staff/team/99999", json={"role": "staff"}).status_code == 404
    assert admin_client.post("/api/staff/team/99999/reset-password").status_code == 404


def test_states_on_the_team_list(admin_client: TestClient, db_session: Session) -> None:
    make_staff(db_session, email="invited@example.com", password=None)
    reset = make_staff(db_session, email="reset@example.com", password=None)
    reset.last_login_at = utc_now()
    make_staff(db_session, email="removed@example.com", active=False, password=None)
    make_staff(db_session, email="active@example.com")
    db_session.flush()
    states = {m["email"]: m["state"] for m in admin_client.get("/api/staff/team").json()}
    assert states == {
        "alex.admin@example.com": "active",
        "invited@example.com": "invited",
        "reset@example.com": "reset_sent",
        "removed@example.com": "removed",
        "active@example.com": "active",
    }


def test_two_admins_removing_each_other_leaves_one(fresh_database_url: str) -> None:
    command.upgrade(alembic_config(fresh_database_url), "head")
    engine = make_engine(fresh_database_url)
    try:
        with Session(engine) as session:
            ids = [
                make_staff(session, role="admin", email=f"admin{n}@example.com").id
                for n in range(2)
            ]
            session.commit()
        barrier = threading.Barrier(2)
        outcomes: list[str] = []

        def remove(actor_id: int, target_id: int) -> None:
            with Session(engine) as session:
                actor = session.get(StaffUser, actor_id)
                target = session.get(StaffUser, target_id)
                assert actor is not None and target is not None
                barrier.wait()
                try:
                    update_staff(session, actor, target, role=None, active=False, now=utc_now())
                    session.commit()
                    outcomes.append("removed")
                except LastAdmin:
                    session.rollback()
                    outcomes.append("refused")

        threads = [
            threading.Thread(target=remove, args=(ids[0], ids[1])),
            threading.Thread(target=remove, args=(ids[1], ids[0])),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert sorted(outcomes) == ["refused", "removed"]
        with Session(engine) as session:
            active = select(func.count()).select_from(StaffUser).where(StaffUser.active)
            assert session.scalar(active) == 1
    finally:
        engine.dispose()


def test_staff_cannot_list_the_team(staff_client: TestClient) -> None:
    assert staff_client.get("/api/staff/team").status_code == 403
