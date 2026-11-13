"""shorten the default slot hold to 5 minutes

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-12 18:00:00.000000

The seed only adds settings that are missing, so a database seeded with the old default
keeps 10 minutes. This moves it to 5, but only if it is still exactly the old default:
a value someone chose on purpose is left alone.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _move(old: int, new: int) -> None:
    op.get_bind().execute(
        sa.text(
            "UPDATE settings SET value = CAST(:new AS jsonb), updated_at = now() "
            "WHERE key = 'slot_hold_minutes' AND value = CAST(:old AS jsonb)"
        ),
        {"new": str(new), "old": str(old)},
    )


def upgrade() -> None:
    _move(10, 5)


def downgrade() -> None:
    _move(5, 10)
