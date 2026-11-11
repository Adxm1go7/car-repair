"""create reservations

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-11 16:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Lets a GiST index compare plain integers (bay_id) alongside ranges.
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.create_table(
        "reservations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("bay_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("during", postgresql.TSTZRANGE(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("kind IN ('booking', 'block')", name=op.f("ck_reservations_kind_valid")),
        sa.CheckConstraint(
            "NOT isempty(during) AND NOT lower_inf(during) AND NOT upper_inf(during)",
            name=op.f("ck_reservations_during_bounded"),
        ),
        sa.ForeignKeyConstraint(["bay_id"], ["bays.id"], name=op.f("fk_reservations_bay_id_bays")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reservations")),
        postgresql.ExcludeConstraint(
            (sa.column("bay_id"), "="),
            (sa.column("during"), "&&"),
            using="gist",
            where=sa.text("active"),
            name="ex_reservations_no_overlap",
        ),
    )


def downgrade() -> None:
    """Downgrade schema. The btree_gist extension is left installed."""
    op.drop_table("reservations")
