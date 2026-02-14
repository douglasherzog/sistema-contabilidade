"""employee thirteenth salary

Revision ID: 5b7c2d3e4f5g_employee_thirteenth
Revises: 4a6b1c2d3e4f
Create Date: 2026-02-14 17:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "5b7c2d3e4f5g"
down_revision = "4a6b1c2d3e4f"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "employee_thirteenth",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("reference_year", sa.Integer(), nullable=False),
        sa.Column("payment_year", sa.Integer(), nullable=False),
        sa.Column("payment_month", sa.Integer(), nullable=False),
        sa.Column("payment_type", sa.String(length=20), nullable=False),
        sa.Column("pay_date", sa.Date(), nullable=True),
        sa.Column("base_salary_at_calc", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("months_worked", sa.Integer(), nullable=False),
        sa.Column("gross_amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("inss_est", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("irrf_est", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("net_est", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["employee_id"], ["employee.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("employee_thirteenth", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_employee_thirteenth_employee_id"), ["employee_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_employee_thirteenth_ref_year"), ["reference_year"], unique=False)
        batch_op.create_index(batch_op.f("ix_employee_thirteenth_payment_year"), ["payment_year"], unique=False)
        batch_op.create_index(batch_op.f("ix_employee_thirteenth_payment_month"), ["payment_month"], unique=False)
        batch_op.create_index("ix_employee_thirteenth_payment", ["payment_year", "payment_month"], unique=False)


def downgrade():
    with op.batch_alter_table("employee_thirteenth", schema=None) as batch_op:
        batch_op.drop_index("ix_employee_thirteenth_payment")
        batch_op.drop_index(batch_op.f("ix_employee_thirteenth_payment_month"))
        batch_op.drop_index(batch_op.f("ix_employee_thirteenth_payment_year"))
        batch_op.drop_index(batch_op.f("ix_employee_thirteenth_ref_year"))
        batch_op.drop_index(batch_op.f("ix_employee_thirteenth_employee_id"))

    op.drop_table("employee_thirteenth")
