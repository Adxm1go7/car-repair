"""enquiries: a customer describes a problem; staff book it in or decline it

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-19 18:00:00.000000

A booked enquiry becomes a confirmed booking with source 'enquiry' and no deposit, like a
phone booking. Enquiry emails are a third kind of email_log subject. Downgrading refuses
while bookings made from enquiries exist: the older checks can't hold them.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "0011"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Copied, not imported: a migration must not change when the model module does.
OLD_SOURCES = "source IN ('online', 'phone')"
SOURCES = "source IN ('online', 'phone', 'enquiry')"
OLD_NOT_REQUIRED = "deposit_status <> 'not_required' OR source = 'phone'"
NOT_REQUIRED = "deposit_status <> 'not_required' OR source IN ('phone', 'enquiry')"
OLD_ONE_SUBJECT = "(booking_id IS NULL) <> (staff_user_id IS NULL)"
ONE_SUBJECT = "num_nonnulls(booking_id, staff_user_id, enquiry_id) = 1"
OLD_EMAIL_TEMPLATES = (
    "'confirmation', 'reminder', 'cancellation', 'moved', 'garage_cancellation', "
    "'staff_invite', 'password_reset', "
    "'request_received', 'approved', 'proposed', 'declined', 'request_expired', 'deposit_expired'"
)
EMAIL_TEMPLATES = f"{OLD_EMAIL_TEMPLATES}, 'enquiry_received', 'enquiry_declined'"


def _replace_check(table: str, name: str, condition: str) -> None:
    op.drop_constraint(op.f(f"ck_{table}_{name}"), table, type_="check")
    op.create_check_constraint(op.f(f"ck_{table}_{name}"), table, condition)


def upgrade() -> None:
    op.create_table(
        "enquiries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=10), server_default="new", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("customer_name", sa.String(length=100), nullable=False),
        sa.Column("customer_phone", sa.String(length=20), nullable=False),
        sa.Column("customer_email", sa.String(length=254), nullable=False),
        sa.Column("car_registration", sa.String(length=8), nullable=False),
        sa.Column("car_make", sa.String(length=50), nullable=False),
        sa.Column("car_model", sa.String(length=50), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("handled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("handled_by", sa.Integer(), nullable=True),
        sa.Column("decline_reason", sa.String(length=500), nullable=True),
        sa.Column("booking_id", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "status IN ('new', 'converted', 'declined')", name=op.f("ck_enquiries_status_valid")
        ),
        sa.CheckConstraint(
            "(status = 'converted') = (booking_id IS NOT NULL)",
            name=op.f("ck_enquiries_booking_only_when_converted"),
        ),
        sa.CheckConstraint(
            "(status = 'new') = (handled_at IS NULL)"
            " AND (handled_at IS NULL) = (handled_by IS NULL)",
            name=op.f("ck_enquiries_handled_unless_new"),
        ),
        sa.ForeignKeyConstraint(
            ["handled_by"], ["staff_users.id"], name=op.f("fk_enquiries_handled_by_staff_users")
        ),
        sa.ForeignKeyConstraint(
            ["booking_id"], ["bookings.id"], name=op.f("fk_enquiries_booking_id_bookings")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_enquiries")),
        sa.UniqueConstraint("booking_id", name=op.f("uq_enquiries_booking_id")),
    )
    op.create_index(
        "ix_enquiries_status_created_at", "enquiries", ["status", "created_at"], unique=False
    )
    op.add_column("email_log", sa.Column("enquiry_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        op.f("fk_email_log_enquiry_id_enquiries"), "email_log", "enquiries", ["enquiry_id"], ["id"]
    )
    op.create_index(op.f("ix_email_log_enquiry_id"), "email_log", ["enquiry_id"], unique=False)
    _replace_check("bookings", "source_valid", SOURCES)
    _replace_check("bookings", "not_required_only_by_phone", NOT_REQUIRED)
    _replace_check("email_log", "has_one_subject", ONE_SUBJECT)
    _replace_check("email_log", "template_valid", f"template IN ({EMAIL_TEMPLATES})")


def downgrade() -> None:
    booked = op.get_bind().scalar(text("SELECT count(*) FROM bookings WHERE source = 'enquiry'"))
    if booked:
        raise RuntimeError(f"{booked} booking(s) came from enquiries; remove them first")
    op.execute("DELETE FROM email_log WHERE enquiry_id IS NOT NULL")
    _replace_check("email_log", "template_valid", f"template IN ({OLD_EMAIL_TEMPLATES})")
    _replace_check("email_log", "has_one_subject", OLD_ONE_SUBJECT)
    _replace_check("bookings", "not_required_only_by_phone", OLD_NOT_REQUIRED)
    _replace_check("bookings", "source_valid", OLD_SOURCES)
    op.drop_index(op.f("ix_email_log_enquiry_id"), table_name="email_log")
    op.drop_constraint(op.f("fk_email_log_enquiry_id_enquiries"), "email_log", type_="foreignkey")
    op.drop_column("email_log", "enquiry_id")
    op.drop_index("ix_enquiries_status_created_at", table_name="enquiries")
    op.drop_table("enquiries")
