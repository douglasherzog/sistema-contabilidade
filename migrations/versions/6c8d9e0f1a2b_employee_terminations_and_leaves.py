"""employee terminations and leaves

Revision ID: 6c8d9e0f1a2b
Revises: 5b7c2d3e4f5g
Create Date: 2026-02-14 15:30:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "6c8d9e0f1a2b"
down_revision = "5b7c2d3e4f5g"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "employee_termination",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("termination_date", sa.Date(), nullable=False),
        sa.Column("termination_type", sa.String(length=40), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.Column("gross_total", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("inss_est", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("irrf_est", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("net_est", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["employee_id"], ["employee.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("employee_termination", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_employee_termination_employee_id"), ["employee_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_employee_termination_year"), ["year"], unique=False)
        batch_op.create_index(batch_op.f("ix_employee_termination_month"), ["month"], unique=False)
        batch_op.create_index("ix_employee_termination_year_month", ["year", "month"], unique=False)

    op.create_table(
        "employee_leave",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("leave_type", sa.String(length=40), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.Column("paid_by", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["employee_id"], ["employee.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("employee_leave", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_employee_leave_employee_id"), ["employee_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_employee_leave_year"), ["year"], unique=False)
        batch_op.create_index(batch_op.f("ix_employee_leave_month"), ["month"], unique=False)
        batch_op.create_index("ix_employee_leave_year_month", ["year", "month"], unique=False)


def downgrade():
    with op.batch_alter_table("employee_leave", schema=None) as batch_op:
        batch_op.drop_index("ix_employee_leave_year_month")
        batch_op.drop_index(batch_op.f("ix_employee_leave_month"))
        batch_op.drop_index(batch_op.f("ix_employee_leave_year"))
        batch_op.drop_index(batch_op.f("ix_employee_leave_employee_id"))
    op.drop_table("employee_leave")

    with op.batch_alter_table("employee_termination", schema=None) as batch_op:
        batch_op.drop_index("ix_employee_termination_year_month")
        batch_op.drop_index(batch_op.f("ix_employee_termination_month"))
        batch_op.drop_index(batch_op.f("ix_employee_termination_year"))
        batch_op.drop_index(batch_op.f("ix_employee_termination_employee_id"))
    op.drop_table("employee_termination")
