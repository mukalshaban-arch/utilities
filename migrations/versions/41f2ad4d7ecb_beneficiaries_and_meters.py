"""beneficiaries and meters

Revision ID: 41f2ad4d7ecb
Revises: d9d402ec0305
Create Date: 2026-07-12 15:42:31.242828

Allocations and expenses move from (user, utility_type) to a specific meter number
belonging to a Beneficiary. Existing employee users are converted into beneficiaries
and their historic rows are attached to placeholder meters, which the admin can
rename to the real meter number afterwards.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '41f2ad4d7ecb'
down_revision = 'd9d402ec0305'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "beneficiary",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("position", sa.String(length=40), nullable=False),
        sa.Column("facility", sa.String(length=40), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "meter",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("beneficiary_id", sa.Integer(), nullable=False),
        sa.Column("utility_type_id", sa.Integer(), nullable=False),
        sa.Column("number", sa.String(length=60), nullable=False),
        sa.ForeignKeyConstraint(["beneficiary_id"], ["beneficiary.id"]),
        sa.ForeignKeyConstraint(["utility_type_id"], ["utility_type.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("utility_type_id", "number", name="uq_meter_number"),
    )

    op.add_column("allocation", sa.Column("meter_id", sa.Integer(), nullable=True))
    op.add_column("expense", sa.Column("meter_id", sa.Integer(), nullable=True))

    bind = op.get_bind()
    beneficiary_of_user = {}

    def beneficiary_for(user_id):
        if user_id not in beneficiary_of_user:
            name = bind.execute(
                sa.text('SELECT name FROM "user" WHERE id = :id'), {"id": user_id}
            ).scalar()
            beneficiary_of_user[user_id] = bind.execute(
                sa.text(
                    "INSERT INTO beneficiary (name, position, facility) "
                    "VALUES (:name, 'Other', NULL) RETURNING id"
                ),
                {"name": name},
            ).scalar()
        return beneficiary_of_user[user_id]

    # Existing employee users become beneficiaries.
    for (user_id,) in bind.execute(
        sa.text("SELECT id FROM \"user\" WHERE role = 'employee'")
    ).fetchall():
        beneficiary_for(user_id)

    # Every (user, utility) pair carrying history needs a meter to hang off.
    pairs = bind.execute(
        sa.text(
            "SELECT DISTINCT user_id, utility_type_id FROM allocation "
            "UNION SELECT DISTINCT user_id, utility_type_id FROM expense"
        )
    ).fetchall()

    for index, (user_id, utility_type_id) in enumerate(pairs, start=1):
        meter_id = bind.execute(
            sa.text(
                "INSERT INTO meter (beneficiary_id, utility_type_id, number) "
                "VALUES (:b, :u, :n) RETURNING id"
            ),
            {"b": beneficiary_for(user_id), "u": utility_type_id, "n": f"TO-BE-SET-{index}"},
        ).scalar()

        params = {"m": meter_id, "u": user_id, "t": utility_type_id}
        bind.execute(
            sa.text("UPDATE allocation SET meter_id = :m WHERE user_id = :u AND utility_type_id = :t"),
            params,
        )
        bind.execute(
            sa.text("UPDATE expense SET meter_id = :m WHERE user_id = :u AND utility_type_id = :t"),
            params,
        )

    op.drop_constraint("uq_allocation_period", "allocation", type_="unique")
    op.drop_column("allocation", "user_id")
    op.drop_column("allocation", "utility_type_id")
    op.alter_column("allocation", "meter_id", nullable=False)
    op.create_foreign_key("fk_allocation_meter", "allocation", "meter", ["meter_id"], ["id"])
    op.create_unique_constraint("uq_allocation_period", "allocation", ["meter_id", "quarter", "year"])

    op.drop_column("expense", "user_id")
    op.drop_column("expense", "utility_type_id")
    op.alter_column("expense", "meter_id", nullable=False)
    op.create_foreign_key("fk_expense_meter", "expense", "meter", ["meter_id"], ["id"])

    # Staff no longer log in; only admins and approvers do.
    bind.execute(
        sa.text(
            "DELETE FROM \"user\" WHERE role = 'employee' AND id NOT IN ("
            "SELECT created_by_id FROM allocation "
            "UNION SELECT created_by_id FROM expense "
            "UNION SELECT approved_by_id FROM expense WHERE approved_by_id IS NOT NULL)"
        )
    )


def downgrade():
    raise NotImplementedError(
        "Downgrade is not supported: meter-level allocations cannot be collapsed back "
        "to (user, utility) without losing which meter the money belonged to."
    )
