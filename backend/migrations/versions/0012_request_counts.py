"""request counts: attempts at the public forms, for the rate limits

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-20 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0012"
down_revision: str | Sequence[str] | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "request_counts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=30), nullable=False),
        sa.Column("ip", sa.String(length=45), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_request_counts")),
    )
    op.create_index(
        "ix_request_counts_action_ip_at", "request_counts", ["action", "ip", "at"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_request_counts_action_ip_at", table_name="request_counts")
    op.drop_table("request_counts")
