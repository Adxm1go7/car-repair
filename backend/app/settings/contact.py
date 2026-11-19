"""The garage's contact details: the `garage_contact` setting, edited by admins.

The site reads it on each request, and the worker when it sends each email, so a change
shows at once there and in every email sent from then on. Nothing here commits.
"""

from datetime import datetime
from typing import Final

from sqlalchemy.orm import Session

from app.models import Setting, StaffUser
from app.staff.audit import record_audit

KEY: Final = "garage_contact"
FIELDS: Final = ("name", "address", "phone", "email")


def read_contact(session: Session) -> dict[str, str]:
    """The four details, each "" if missing (so a damaged setting can still be fixed)."""
    setting = session.get(Setting, KEY)
    value = setting.value if setting is not None and isinstance(setting.value, dict) else {}
    return {field: str(value.get(field, "")) for field in FIELDS}


def save_contact(
    session: Session, admin: StaffUser, contact: dict[str, str], now: datetime
) -> dict[str, str]:
    """Save already-cleaned details. Writes an audit entry only when something changed."""
    setting = session.get(Setting, KEY, with_for_update=True)
    before = read_contact(session)
    after = {field: contact[field] for field in FIELDS}
    if setting is not None and after == before and setting.value == after:
        return after
    if setting is None:
        session.add(Setting(key=KEY, value=after))
    else:
        setting.value = after  # a new dict, so the JSONB column is seen as changed
    session.flush()
    # The setting has no numeric id; 0 stands for "the garage's contact details".
    record_audit(
        session, admin, "contact.update", "setting", 0, before=before, after=after, now=now
    )
    return after
