"""opening hours timetables: hours in force from a date

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-18 12:00:00.000000

Existing hours and breaks move into a first timetable starting 2000-01-01. Downgrading
refuses while more than one timetable exists: the older tables hold a single week.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Copied, not imported: a migration must not change when the model module does.
FIRST_TIMETABLE_STARTS = "2000-01-01"


def upgrade() -> None:
    op.create_table(
        "timetables",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["staff_users.id"], name=op.f("fk_timetables_created_by_staff_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_timetables")),
        sa.UniqueConstraint("starts_on", name=op.f("uq_timetables_starts_on")),
    )
    op.add_column("opening_hours", sa.Column("timetable_id", sa.Integer(), nullable=True))
    op.add_column("opening_hours_breaks", sa.Column("timetable_id", sa.Integer(), nullable=True))

    # Today's week becomes the first timetable. An empty database stays empty: the seed
    # creates the first timetable there.
    connection = op.get_bind()
    if connection.execute(sa.text("SELECT EXISTS (SELECT 1 FROM opening_hours)")).scalar():
        first = connection.execute(
            sa.text("INSERT INTO timetables (starts_on) VALUES (:starts) RETURNING id"),
            {"starts": FIRST_TIMETABLE_STARTS},
        ).scalar_one()
        connection.execute(sa.text("UPDATE opening_hours SET timetable_id = :id"), {"id": first})
        connection.execute(
            sa.text("UPDATE opening_hours_breaks SET timetable_id = :id"), {"id": first}
        )

    op.drop_constraint(
        "fk_opening_hours_breaks_weekday_opening_hours", "opening_hours_breaks", type_="foreignkey"
    )
    op.drop_constraint("pk_opening_hours", "opening_hours", type_="primary")
    op.alter_column("opening_hours", "timetable_id", nullable=False)
    op.alter_column("opening_hours_breaks", "timetable_id", nullable=False)
    op.create_primary_key("pk_opening_hours", "opening_hours", ["timetable_id", "weekday"])
    op.create_foreign_key(
        op.f("fk_opening_hours_timetable_id_timetables"),
        "opening_hours",
        "timetables",
        ["timetable_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        op.f("fk_opening_hours_breaks_timetable_id_opening_hours"),
        "opening_hours_breaks",
        "opening_hours",
        ["timetable_id", "weekday"],
        ["timetable_id", "weekday"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    connection = op.get_bind()
    if connection.execute(sa.text("SELECT count(*) FROM timetables")).scalar_one() > 1:
        raise RuntimeError(
            "Can't downgrade: more than one timetable exists. Delete the extra ones first."
        )
    op.drop_constraint(
        "fk_opening_hours_breaks_timetable_id_opening_hours",
        "opening_hours_breaks",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_opening_hours_timetable_id_timetables", "opening_hours", type_="foreignkey"
    )
    op.drop_constraint("pk_opening_hours", "opening_hours", type_="primary")
    op.drop_column("opening_hours_breaks", "timetable_id")
    op.drop_column("opening_hours", "timetable_id")
    op.create_primary_key("pk_opening_hours", "opening_hours", ["weekday"])
    op.create_foreign_key(
        op.f("fk_opening_hours_breaks_weekday_opening_hours"),
        "opening_hours_breaks",
        "opening_hours",
        ["weekday"],
        ["weekday"],
        ondelete="CASCADE",
    )
    op.drop_table("timetables")
