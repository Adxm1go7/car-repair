"""The audit log: one row per staff change, added in the change's own transaction, so an
entry exists exactly when its change was committed."""

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditEntry, StaffUser


def record_audit(
    session: Session,
    staff: StaffUser | None,
    action: str,
    entity_type: str,
    entity_id: int,
    *,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    reason: str | None = None,
    booking_reference: str | None = None,
    now: datetime,
) -> AuditEntry:
    """Add an entry and flush. `staff` is None only for the create_admin command."""
    entry = AuditEntry(
        staff_user_id=staff.id if staff is not None else None,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        booking_reference=booking_reference,
        before=before,
        after=after,
        reason=reason,
        at=now,
    )
    session.add(entry)
    session.flush()
    return entry
