"""create email_log and booking_links

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-14 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Copied, not imported: a migration must not change when the model module does.
EMAIL_TEMPLATES = "'confirmation', 'reminder', 'cancellation'"
EMAIL_STATUSES = "'queued', 'sent', 'failed', 'skipped'"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "email_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("template", sa.String(length=20), nullable=False),
        sa.Column("booking_id", sa.Integer(), nullable=True),
        sa.Column("recipient", sa.String(length=254), nullable=False),
        sa.Column("status", sa.String(length=10), server_default="queued", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            f"template IN ({EMAIL_TEMPLATES})", name=op.f("ck_email_log_template_valid")
        ),
        sa.CheckConstraint(f"status IN ({EMAIL_STATUSES})", name=op.f("ck_email_log_status_valid")),
        sa.CheckConstraint("attempts >= 0", name=op.f("ck_email_log_attempts_non_negative")),
        sa.ForeignKeyConstraint(
            ["booking_id"], ["bookings.id"], name=op.f("fk_email_log_booking_id_bookings")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_email_log")),
    )
    op.create_index(
        "ix_email_log_status_next_attempt_at", "email_log", ["status", "next_attempt_at"]
    )
    op.create_index(
        "ux_email_log_one_reminder",
        "email_log",
        ["booking_id"],
        unique=True,
        postgresql_where=sa.text("template = 'reminder'"),
    )

    op.create_table(
        "booking_links",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("booking_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["booking_id"], ["bookings.id"], name=op.f("fk_booking_links_booking_id_bookings")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_booking_links")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_booking_links_token_hash")),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("booking_links")
    op.drop_index("ux_email_log_one_reminder", table_name="email_log")
    op.drop_index("ix_email_log_status_next_attempt_at", table_name="email_log")
    op.drop_table("email_log")
