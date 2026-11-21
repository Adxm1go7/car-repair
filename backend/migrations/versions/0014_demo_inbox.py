"""demo inbox: on the live demo site, the emails the worker would have sent

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-21 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0014"
down_revision: str | Sequence[str] | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "demo_inbox",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("template", sa.String(30), nullable=False),
        sa.Column("recipient", sa.String(254), nullable=False),
        sa.Column("subject", sa.String(300), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("html", sa.Text(), nullable=False),
        sa.Column(
            "sent_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_demo_inbox_recipient_id", "demo_inbox", ["recipient", "id"])


def downgrade() -> None:
    op.drop_index("ix_demo_inbox_recipient_id", table_name="demo_inbox")
    op.drop_table("demo_inbox")
