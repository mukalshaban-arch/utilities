"""activity log

Revision ID: f92898f24d79
Revises: 568bb3e83e81
Create Date: 2026-07-12 17:10:46.970282

Existing allocations pre-date the log, and their original timestamp was never
recorded. They are backfilled with the action 'Allocated (pre-log)' so the entry
is honest about the timestamp being the migration time, not the real one.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f92898f24d79'
down_revision = '568bb3e83e81'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "activity_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("beneficiary_name", sa.String(length=120), nullable=False),
        sa.Column("unit", sa.String(length=40), nullable=True),
        sa.Column("utility", sa.String(length=80), nullable=True),
        sa.Column("number", sa.String(length=60), nullable=True),
        sa.Column("quarter", sa.Integer(), nullable=True),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_activity_log_created_at", "activity_log", ["created_at"])

    op.get_bind().execute(
        sa.text(
            """
            INSERT INTO activity_log
                (created_at, user_id, action, beneficiary_name, unit, utility, number, quarter, year, amount)
            SELECT
                now() AT TIME ZONE 'UTC',  -- the app stores naive UTC; keep these comparable
                a.created_by_id,
                'Allocated (pre-log)',
                b.name,
                COALESCE(b.facility, b.department),
                t.name,
                m.number,
                a.quarter,
                a.year,
                a.amount
            FROM allocation a
            JOIN meter m ON m.id = a.meter_id
            JOIN beneficiary b ON b.id = m.beneficiary_id
            JOIN utility_type t ON t.id = m.utility_type_id
            """
        )
    )


def downgrade():
    op.drop_index("ix_activity_log_created_at", table_name="activity_log")
    op.drop_table("activity_log")
