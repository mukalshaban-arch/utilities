"""drop expense tracking

Revision ID: efbaeaf9d4e1
Revises: 41f2ad4d7ecb
Create Date: 2026-07-12 16:12:46.800840

The system now tracks allocations only. Expenses, the approval workflow and the
approver role are removed.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'efbaeaf9d4e1'
down_revision = '41f2ad4d7ecb'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_table("expense")

    # Approvers had nothing left to approve.
    op.get_bind().execute(sa.text("DELETE FROM \"user\" WHERE role = 'approver'"))


def downgrade():
    raise NotImplementedError(
        "Downgrade is not supported: dropping the expense table discards its rows."
    )
