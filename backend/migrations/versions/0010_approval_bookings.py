"""approval bookings: the awaiting-deposit status and the approval emails

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-19 12:00:00.000000

A request (pending_approval) and an approved booking waiting for its deposit
(awaiting_deposit) keep their deadline in hold_expires_at, like a hold. The approval
settings are setup data, added by the seed command like the other booking rules.
Downgrading refuses while awaiting-deposit bookings exist: the older checks can't hold them.
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Copied, not imported: a migration must not change when the model module does.
OLD_STATUSES = (
    "'held', 'pending_approval', 'confirmed', 'in_progress', "
    "'completed', 'cancelled', 'no_show', 'expired'"
)
STATUSES = OLD_STATUSES + ", 'awaiting_deposit'"
OLD_HAS_EXPIRY = "status <> 'held' OR hold_expires_at IS NOT NULL"
HAS_EXPIRY = (
    "status NOT IN ('held', 'pending_approval', 'awaiting_deposit') OR hold_expires_at IS NOT NULL"
)
OLD_EMAIL_TEMPLATES = (
    "'confirmation', 'reminder', 'cancellation', 'moved', 'garage_cancellation', "
    "'staff_invite', 'password_reset'"
)
NEW_EMAIL_TEMPLATES = (
    "'request_received', 'approved', 'proposed', 'declined', 'request_expired', 'deposit_expired'"
)
EMAIL_TEMPLATES = f"{OLD_EMAIL_TEMPLATES}, {NEW_EMAIL_TEMPLATES}"


def _replace_check(table: str, name: str, condition: str) -> None:
    op.drop_constraint(op.f(f"ck_{table}_{name}"), table, type_="check")
    op.create_check_constraint(op.f(f"ck_{table}_{name}"), table, condition)


def upgrade() -> None:
    _replace_check("bookings", "status_valid", f"status IN ({STATUSES})")
    _replace_check("bookings", "held_has_expiry", HAS_EXPIRY)
    _replace_check("email_log", "template_valid", f"template IN ({EMAIL_TEMPLATES})")


def downgrade() -> None:
    waiting = op.get_bind().scalar(
        text("SELECT count(*) FROM bookings WHERE status = 'awaiting_deposit'")
    )
    if waiting:
        raise RuntimeError(
            f"{waiting} booking(s) are awaiting their deposit; confirm or cancel them first"
        )
    op.execute(
        "DELETE FROM email_log WHERE template IN ('request_received', 'approved', 'proposed',"
        " 'declined', 'request_expired', 'deposit_expired')"
    )
    _replace_check("email_log", "template_valid", f"template IN ({OLD_EMAIL_TEMPLATES})")
    _replace_check("bookings", "held_has_expiry", OLD_HAS_EXPIRY)
    _replace_check("bookings", "status_valid", f"status IN ({OLD_STATUSES})")
