"""allocation month to quarter

Revision ID: d9d402ec0305
Revises: 5f8656d7cb2a
Create Date: 2026-07-11 23:55:58.454654

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd9d402ec0305'
down_revision = '5f8656d7cb2a'
branch_labels = None
depends_on = None


def upgrade():
    # Add quarter, derive it from the existing month, then drop month.
    op.add_column("allocation", sa.Column("quarter", sa.Integer(), nullable=True))
    op.execute("UPDATE allocation SET quarter = (month - 1) / 3 + 1")
    op.alter_column("allocation", "quarter", nullable=False)
    op.drop_constraint("uq_allocation_period", "allocation", type_="unique")
    op.drop_column("allocation", "month")
    op.create_unique_constraint(
        "uq_allocation_period", "allocation", ["user_id", "utility_type_id", "quarter", "year"]
    )


def downgrade():
    # Reverse: recreate month from the first month of the quarter.
    op.add_column("allocation", sa.Column("month", sa.Integer(), nullable=True))
    op.execute("UPDATE allocation SET month = (quarter - 1) * 3 + 1")
    op.alter_column("allocation", "month", nullable=False)
    op.drop_constraint("uq_allocation_period", "allocation", type_="unique")
    op.drop_column("allocation", "quarter")
    op.create_unique_constraint(
        "uq_allocation_period", "allocation", ["user_id", "utility_type_id", "month", "year"]
    )
