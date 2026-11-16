from datetime import UTC, datetime

from factories import make_staff
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditEntry
from app.staff.audit import record_audit

NOW = datetime(2026, 11, 16, 9, tzinfo=UTC)


def test_record_audit_writes_one_row(db_session: Session) -> None:
    user = make_staff(db_session)
    record_audit(
        db_session,
        user,
        "booking.move",
        "booking",
        7,
        before={"start": "09:00"},
        after={"start": "10:00"},
        reason="Lift broken",
        booking_reference="ABCD-EFGH",
        now=NOW,
    )
    entry = db_session.scalars(select(AuditEntry)).one()
    assert (entry.staff_user_id, entry.action, entry.entity_id) == (user.id, "booking.move", 7)
    assert entry.before == {"start": "09:00"}
    assert entry.reason == "Lift broken"
    assert entry.at == NOW


def test_record_audit_without_a_user(db_session: Session) -> None:
    record_audit(db_session, None, "staff.invite", "staff_user", 1, now=NOW)
    assert db_session.scalars(select(AuditEntry.staff_user_id)).one() is None
