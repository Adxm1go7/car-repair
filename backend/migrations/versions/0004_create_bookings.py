"""create bookings

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-12 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Copied, not imported: a migration must not change when the model module does.
STATUSES = (
    "'held', 'pending_approval', 'confirmed', 'in_progress', "
    "'completed', 'cancelled', 'no_show', 'expired'"
)
CONFIRMED_HAS_DETAILS = (
    "status <> 'confirmed' OR (customer_name IS NOT NULL AND customer_phone IS NOT NULL"
    " AND customer_email IS NOT NULL AND car_registration IS NOT NULL"
    " AND car_make IS NOT NULL AND car_model IS NOT NULL)"
)


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "bookings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("reference", sa.String(length=9), nullable=False),
        sa.Column("reservation_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("hold_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hold_token_hash", sa.String(length=64), nullable=True),
        sa.Column("customer_name", sa.String(length=100), nullable=True),
        sa.Column("customer_phone", sa.String(length=20), nullable=True),
        sa.Column("customer_email", sa.String(length=254), nullable=True),
        sa.Column("car_registration", sa.String(length=8), nullable=True),
        sa.Column("car_make", sa.String(length=50), nullable=True),
        sa.Column("car_model", sa.String(length=50), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(f"status IN ({STATUSES})", name=op.f("ck_bookings_status_valid")),
        sa.CheckConstraint("start_at < end_at", name=op.f("ck_bookings_start_before_end")),
        sa.CheckConstraint(
            "status <> 'held' OR hold_expires_at IS NOT NULL",
            name=op.f("ck_bookings_held_has_expiry"),
        ),
        sa.CheckConstraint(
            "status <> 'held' OR hold_token_hash IS NOT NULL",
            name=op.f("ck_bookings_held_has_token"),
        ),
        sa.CheckConstraint(CONFIRMED_HAS_DETAILS, name=op.f("ck_bookings_confirmed_has_details")),
        sa.ForeignKeyConstraint(
            ["reservation_id"],
            ["reservations.id"],
            name=op.f("fk_bookings_reservation_id_reservations"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bookings")),
        sa.UniqueConstraint("reference", name=op.f("uq_bookings_reference")),
        sa.UniqueConstraint("reservation_id", name=op.f("uq_bookings_reservation_id")),
    )
    op.create_index("ix_bookings_status_hold_expires_at", "bookings", ["status", "hold_expires_at"])
    op.create_table(
        "booking_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("booking_id", sa.Integer(), nullable=False),
        sa.Column("service_id", sa.Integer(), nullable=False),
        sa.Column("service_name", sa.String(length=100), nullable=False),
        sa.Column("price_from_pence", sa.Integer(), nullable=False),
        sa.Column("price_to_pence", sa.Integer(), nullable=True),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.CheckConstraint("duration_minutes > 0", name=op.f("ck_booking_items_duration_positive")),
        sa.CheckConstraint(
            "price_from_pence >= 0", name=op.f("ck_booking_items_price_from_non_negative")
        ),
        sa.CheckConstraint(
            "price_to_pence IS NULL OR price_to_pence >= price_from_pence",
            name=op.f("ck_booking_items_price_range_ordered"),
        ),
        sa.ForeignKeyConstraint(
            ["booking_id"],
            ["bookings.id"],
            name=op.f("fk_booking_items_booking_id_bookings"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["service_id"],
            ["services.id"],
            name=op.f("fk_booking_items_service_id_services"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_booking_items")),
        sa.UniqueConstraint("booking_id", "position", name="uq_booking_items_booking_id_position"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("booking_items")
    op.drop_index("ix_bookings_status_hold_expires_at", table_name="bookings")
    op.drop_table("bookings")
