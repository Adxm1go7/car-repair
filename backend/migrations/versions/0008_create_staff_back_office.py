"""create staff accounts, blocks and the audit log; phone bookings

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-16 12:00:00.000000

Downgrading refuses while phone bookings without an email or deposit exist: the older
checks can't hold them.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Copied, not imported: a migration must not change when the model module does.
OLD_DEPOSIT_STATUSES = "'unpaid', 'paid', 'refund_pending', 'refunded', 'refund_failed', 'waived'"
DEPOSIT_STATUSES = OLD_DEPOSIT_STATUSES + ", 'not_required'"
OLD_CONFIRMED_HAS_DETAILS = (
    "status <> 'confirmed' OR (customer_name IS NOT NULL AND customer_phone IS NOT NULL"
    " AND customer_email IS NOT NULL AND car_registration IS NOT NULL"
    " AND car_make IS NOT NULL AND car_model IS NOT NULL)"
)
CONFIRMED_HAS_DETAILS = (
    "status <> 'confirmed' OR (customer_name IS NOT NULL AND customer_phone IS NOT NULL"
    " AND car_registration IS NOT NULL AND car_make IS NOT NULL AND car_model IS NOT NULL"
    " AND (customer_email IS NOT NULL OR source = 'phone'))"
)
OLD_EMAIL_TEMPLATES = "'confirmation', 'reminder', 'cancellation'"
EMAIL_TEMPLATES = (
    OLD_EMAIL_TEMPLATES + ", 'moved', 'garage_cancellation', 'staff_invite', 'password_reset'"
)


def _created_at() -> sa.Column[sa.DateTime]:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "staff_users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("password_hash", sa.String(length=200), nullable=True),
        sa.Column("role", sa.String(length=10), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        _created_at(),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("role IN ('admin', 'staff')", name=op.f("ck_staff_users_role_valid")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_staff_users")),
        sa.UniqueConstraint("email", name=op.f("uq_staff_users_email")),
    )

    op.create_table(
        "staff_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("staff_user_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["staff_user_id"],
            ["staff_users.id"],
            name=op.f("fk_staff_sessions_staff_user_id_staff_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_staff_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_staff_sessions_token_hash")),
    )

    op.create_table(
        "password_tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("staff_user_id", sa.Integer(), nullable=False),
        sa.Column("purpose", sa.String(length=10), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
        sa.CheckConstraint(
            "purpose IN ('invite', 'reset')", name=op.f("ck_password_tokens_purpose_valid")
        ),
        sa.ForeignKeyConstraint(
            ["staff_user_id"],
            ["staff_users.id"],
            name=op.f("fk_password_tokens_staff_user_id_staff_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_password_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_password_tokens_token_hash")),
    )

    op.create_table(
        "login_attempts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("ip", sa.String(length=45), nullable=False),
        sa.Column("succeeded", sa.Boolean(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_login_attempts")),
    )
    op.create_index("ix_login_attempts_email_at", "login_attempts", ["email", "at"])
    op.create_index("ix_login_attempts_ip_at", "login_attempts", ["ip", "at"])

    op.create_table(
        "blocks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("note", sa.String(length=200), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("all_bays", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        _created_at(),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["created_by"], ["staff_users.id"], name=op.f("fk_blocks_created_by_staff_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_blocks")),
    )

    op.create_table(
        "audit_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("staff_user_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("entity_type", sa.String(length=20), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("booking_reference", sa.String(length=9), nullable=True),
        sa.Column("before", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["staff_user_id"],
            ["staff_users.id"],
            name=op.f("fk_audit_entries_staff_user_id_staff_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_entries")),
    )
    op.create_index("ix_audit_entries_at", "audit_entries", ["at"])
    op.create_index("ix_audit_entries_staff_user_id", "audit_entries", ["staff_user_id"])
    op.create_index("ix_audit_entries_booking_reference", "audit_entries", ["booking_reference"])

    # Bookings: where they came from, who made a phone booking, and no deposit for those.
    op.add_column(
        "bookings",
        sa.Column("source", sa.String(length=10), server_default="online", nullable=False),
    )
    op.add_column("bookings", sa.Column("created_by", sa.Integer(), nullable=True))
    op.add_column(
        "bookings", sa.Column("status_changed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_foreign_key(
        op.f("fk_bookings_created_by_staff_users"),
        "bookings",
        "staff_users",
        ["created_by"],
        ["id"],
    )
    op.create_check_constraint(
        op.f("ck_bookings_source_valid"), "bookings", "source IN ('online', 'phone')"
    )
    _replace_check("bookings", "deposit_status_valid", f"deposit_status IN ({DEPOSIT_STATUSES})")
    _replace_check(
        "bookings",
        "confirmed_has_deposit",
        "status <> 'confirmed' OR deposit_status IN ('paid', 'waived', 'not_required')",
    )
    op.create_check_constraint(
        op.f("ck_bookings_not_required_only_by_phone"),
        "bookings",
        "deposit_status <> 'not_required' OR source = 'phone'",
    )
    _replace_check("bookings", "confirmed_has_details", CONFIRMED_HAS_DETAILS)

    # Reservations: a block's reservations point at it.
    op.add_column("reservations", sa.Column("block_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        op.f("fk_reservations_block_id_blocks"), "reservations", "blocks", ["block_id"], ["id"]
    )
    op.create_check_constraint(
        op.f("ck_reservations_block_has_block"),
        "reservations",
        "kind <> 'block' OR block_id IS NOT NULL",
    )

    # Email: staff emails, and the context a move or garage cancellation needs.
    op.alter_column(
        "email_log", "template", type_=sa.String(length=30), existing_type=sa.String(length=20)
    )
    op.add_column("email_log", sa.Column("staff_user_id", sa.Integer(), nullable=True))
    op.add_column(
        "email_log",
        sa.Column("context", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_foreign_key(
        op.f("fk_email_log_staff_user_id_staff_users"),
        "email_log",
        "staff_users",
        ["staff_user_id"],
        ["id"],
    )
    _replace_check("email_log", "template_valid", f"template IN ({EMAIL_TEMPLATES})")
    op.create_check_constraint(
        op.f("ck_email_log_has_one_subject"),
        "email_log",
        "(booking_id IS NULL) <> (staff_user_id IS NULL)",
    )


def _replace_check(table: str, name: str, condition: str) -> None:
    op.drop_constraint(op.f(f"ck_{table}_{name}"), table, type_="check")
    op.create_check_constraint(op.f(f"ck_{table}_{name}"), table, condition)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(op.f("ck_email_log_has_one_subject"), "email_log", type_="check")
    op.execute("DELETE FROM email_log WHERE staff_user_id IS NOT NULL")
    op.execute("DELETE FROM email_log WHERE template IN ('moved', 'garage_cancellation')")
    _replace_check("email_log", "template_valid", f"template IN ({OLD_EMAIL_TEMPLATES})")
    op.drop_constraint(
        op.f("fk_email_log_staff_user_id_staff_users"), "email_log", type_="foreignkey"
    )
    op.drop_column("email_log", "context")
    op.drop_column("email_log", "staff_user_id")
    op.alter_column(
        "email_log", "template", type_=sa.String(length=20), existing_type=sa.String(length=30)
    )

    op.drop_constraint(op.f("ck_reservations_block_has_block"), "reservations", type_="check")
    op.execute("DELETE FROM reservations WHERE kind = 'block'")
    op.drop_constraint(op.f("fk_reservations_block_id_blocks"), "reservations", type_="foreignkey")
    op.drop_column("reservations", "block_id")

    _replace_check("bookings", "confirmed_has_details", OLD_CONFIRMED_HAS_DETAILS)
    op.drop_constraint(op.f("ck_bookings_not_required_only_by_phone"), "bookings", type_="check")
    _replace_check(
        "bookings",
        "confirmed_has_deposit",
        "status <> 'confirmed' OR deposit_status IN ('paid', 'waived')",
    )
    _replace_check(
        "bookings", "deposit_status_valid", f"deposit_status IN ({OLD_DEPOSIT_STATUSES})"
    )
    op.drop_constraint(op.f("ck_bookings_source_valid"), "bookings", type_="check")
    op.drop_constraint(op.f("fk_bookings_created_by_staff_users"), "bookings", type_="foreignkey")
    op.drop_column("bookings", "status_changed_at")
    op.drop_column("bookings", "created_by")
    op.drop_column("bookings", "source")

    op.drop_index("ix_audit_entries_booking_reference", table_name="audit_entries")
    op.drop_index("ix_audit_entries_staff_user_id", table_name="audit_entries")
    op.drop_index("ix_audit_entries_at", table_name="audit_entries")
    op.drop_table("audit_entries")
    op.drop_table("blocks")
    op.drop_index("ix_login_attempts_ip_at", table_name="login_attempts")
    op.drop_index("ix_login_attempts_email_at", table_name="login_attempts")
    op.drop_table("login_attempts")
    op.drop_table("password_tokens")
    op.drop_table("staff_sessions")
    op.drop_table("staff_users")
