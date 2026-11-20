"""details removed at: when the 12-month rule blanked a booking's or enquiry's customer details

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-20 14:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0013"
down_revision: str | Sequence[str] | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("bookings", sa.Column("details_removed_at", sa.DateTime(timezone=True)))
    op.add_column("enquiries", sa.Column("details_removed_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("enquiries", "details_removed_at")
    op.drop_column("bookings", "details_removed_at")
