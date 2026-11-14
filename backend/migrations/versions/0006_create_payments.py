"""create payments

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-14 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Copied, not imported: a migration must not change when the model module does.
DEPOSIT_STATUSES = "'unpaid', 'paid', 'refund_pending', 'refunded', 'refund_failed', 'waived'"
STATUS_SUITS_KIND = (
    "(kind = 'deposit' AND refund_of IS NULL AND status IN ('open', 'paid', 'expired'))"
    " OR (kind = 'refund' AND refund_of IS NOT NULL"
    " AND status IN ('pending', 'succeeded', 'failed'))"
)


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "bookings",
        sa.Column("deposit_status", sa.String(length=20), server_default="unpaid", nullable=False),
    )
    # Bookings confirmed before deposits existed were never asked for one.
    op.execute("UPDATE bookings SET deposit_status = 'waived' WHERE status = 'confirmed'")
    op.create_check_constraint(
        op.f("ck_bookings_deposit_status_valid"),
        "bookings",
        f"deposit_status IN ({DEPOSIT_STATUSES})",
    )
    op.create_check_constraint(
        op.f("ck_bookings_confirmed_has_deposit"),
        "bookings",
        "status <> 'confirmed' OR deposit_status IN ('paid', 'waived')",
    )

    op.create_table(
        "payments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("booking_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("provider", sa.String(length=10), nullable=False),
        sa.Column("provider_ref", sa.String(length=255), nullable=False),
        sa.Column("payment_intent_ref", sa.String(length=255), nullable=True),
        sa.Column("amount_pence", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="gbp", nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("refund_of", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("kind IN ('deposit', 'refund')", name=op.f("ck_payments_kind_valid")),
        sa.CheckConstraint(STATUS_SUITS_KIND, name=op.f("ck_payments_status_suits_kind")),
        sa.CheckConstraint("amount_pence > 0", name=op.f("ck_payments_amount_positive")),
        sa.ForeignKeyConstraint(
            ["booking_id"], ["bookings.id"], name=op.f("fk_payments_booking_id_bookings")
        ),
        sa.ForeignKeyConstraint(
            ["refund_of"], ["payments.id"], name=op.f("fk_payments_refund_of_payments")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payments")),
        sa.UniqueConstraint("provider", "provider_ref", name="uq_payments_provider_provider_ref"),
    )
    op.create_index(
        "ux_payments_one_open_deposit",
        "payments",
        ["booking_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'deposit' AND status = 'open'"),
    )
    op.create_index(
        "ux_payments_one_live_refund",
        "payments",
        ["refund_of"],
        unique=True,
        postgresql_where=sa.text("kind = 'refund' AND status <> 'failed'"),
    )

    op.create_table(
        "payment_events",
        sa.Column("provider", sa.String(length=10), nullable=False),
        sa.Column("event_id", sa.String(length=255), nullable=False),
        sa.Column("type", sa.String(length=100), nullable=False),
        sa.Column(
            "received_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("provider", "event_id", name=op.f("pk_payment_events")),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("payment_events")
    op.drop_index("ux_payments_one_live_refund", table_name="payments")
    op.drop_index("ux_payments_one_open_deposit", table_name="payments")
    op.drop_table("payments")
    op.drop_constraint(op.f("ck_bookings_confirmed_has_deposit"), "bookings", type_="check")
    op.drop_constraint(op.f("ck_bookings_deposit_status_valid"), "bookings", type_="check")
    op.drop_column("bookings", "deposit_status")
