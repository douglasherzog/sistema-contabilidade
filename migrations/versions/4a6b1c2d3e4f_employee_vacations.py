"""employee vacations

Revision ID: 4a6b1c2d3e4f
Revises: 2c3d4e5f6a7b
Create Date: 2026-02-14 16:30:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "4a6b1c2d3e4f"
down_revision = "2c3d4e5f6a7b"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "employee_vacation",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("days", sa.Integer(), nullable=False),
        sa.Column("sell_days", sa.Integer(), nullable=False),
        sa.Column("pay_date", sa.Date(), nullable=True),
        sa.Column("base_salary_at_calc", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("vacation_pay", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("vacation_one_third", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("abono_pay", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("abono_one_third", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("gross_total", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("inss_est", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("irrf_est", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("net_est", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["employee_id"], ["employee.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("employee_vacation", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_employee_vacation_employee_id"), ["employee_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_employee_vacation_month"), ["month"], unique=False)
        batch_op.create_index(batch_op.f("ix_employee_vacation_year"), ["year"], unique=False)
        batch_op.create_index("ix_employee_vacation_year_month", ["year", "month"], unique=False)


def downgrade():
    with op.batch_alter_table("employee_vacation", schema=None) as batch_op:
        batch_op.drop_index("ix_employee_vacation_year_month")
        batch_op.drop_index(batch_op.f("ix_employee_vacation_year"))
        batch_op.drop_index(batch_op.f("ix_employee_vacation_month"))
        batch_op.drop_index(batch_op.f("ix_employee_vacation_employee_id"))

    op.drop_table("employee_vacation")
